from pathlib import Path
from datetime import datetime,timedelta,timezone
import csv,json,re,hashlib,uuid
import streamlit as st
import joblib,hmac,os
from sqlalchemy import create_engine,Column,Integer,String,Text,Boolean,DateTime,Float
from sqlalchemy.orm import declarative_base,sessionmaker

def utc_now():
 # SQLite stores naive datetimes; retain UTC semantics without deprecated utcnow.
 return datetime.now(timezone.utc).replace(tzinfo=None)

R=Path(__file__).resolve().parent
engine=create_engine(f"sqlite:///{R/'sti_app.db'}",connect_args={"check_same_thread":False})
Session=sessionmaker(bind=engine); Base=declarative_base()
class User(Base):
 __tablename__="users"; id=Column(Integer,primary_key=True); username=Column(String,unique=True,nullable=False); password_hash=Column(String,nullable=False); role=Column(String,default="admin"); active=Column(Boolean,default=True); created_at=Column(DateTime,default=utc_now)
class Content(Base):
 __tablename__="content"; id=Column(Integer,primary_key=True); topic=Column(String); language=Column(String); title=Column(String); body=Column(Text); source=Column(String); version=Column(String); status=Column(String,default="pending_review"); reviewer=Column(String); reviewed_at=Column(DateTime); created_at=Column(DateTime,default=utc_now); updated_at=Column(DateTime,default=utc_now)
class Inquiry(Base):
 __tablename__="inquiries"; id=Column(Integer,primary_key=True); session_hash=Column(String); language=Column(String); intent=Column(String); entities_json=Column(Text); raw_text=Column(Text); consent_to_store=Column(Boolean); created_at=Column(DateTime,default=utc_now)
class Audit(Base):
 __tablename__="audit_logs"; id=Column(Integer,primary_key=True); actor=Column(String); action=Column(String); object_type=Column(String); object_id=Column(String); details=Column(Text); created_at=Column(DateTime,default=utc_now)
class DemographicProfile(Base):
 __tablename__="demographic_profiles"; id=Column(Integer,primary_key=True); session_hash=Column(String,index=True); gender=Column(String); age_bracket=Column(String); sexually_active=Column(String); residence=Column(String); nearest_health_facility=Column(String); consent_to_store=Column(Boolean,default=False); created_at=Column(DateTime,default=utc_now)
class UsageSession(Base):
 __tablename__="usage_sessions"; id=Column(Integer,primary_key=True); session_id=Column(String,unique=True,index=True); user_hash=Column(String,index=True); started_at=Column(DateTime,default=utc_now); last_activity_at=Column(DateTime,default=utc_now); ended_at=Column(DateTime); user_messages=Column(Integer,default=0); assistant_responses=Column(Integer,default=0); completed_responses=Column(Integer,default=0); dropped_off=Column(Boolean,default=False)
class UsageEvent(Base):
 __tablename__="usage_events"; id=Column(Integer,primary_key=True); session_id=Column(String,index=True); user_hash=Column(String,index=True); event_type=Column(String,index=True); topic=Column(String,index=True); link_category=Column(String,index=True); created_at=Column(DateTime,default=utc_now)
def hash_password(password,salt=None):
 salt=salt or os.urandom(16)
 key=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,200000)
 return f"pbkdf2_sha256$200000${salt.hex()}${key.hex()}"
def verify_password(password,stored):
 try:
  alg,it,salt_hex,key_hex=stored.split("$")
  key=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt_hex),int(it))
  return hmac.compare_digest(key.hex(),key_hex)
 except Exception:return False
def secret_value(name,default=None):
 try:return st.secrets[name]
 except Exception:return os.environ.get(name,default)
def usage_ids():
 if "_usage_user" not in st.session_state: st.session_state["_usage_user"]=uuid.uuid4().hex
 if "_usage_session" not in st.session_state: st.session_state["_usage_session"]=uuid.uuid4().hex
 user_hash=hashlib.sha256(st.session_state["_usage_user"].encode()).hexdigest()[:24]
 return user_hash,st.session_state["_usage_session"]
def usage_event(event_type,topic=None,link_category=None):
 user_hash,sid=usage_ids(); db=Session(); now=utc_now()
 us=db.query(UsageSession).filter_by(session_id=sid).first()
 if not us:
  us=UsageSession(session_id=sid,user_hash=user_hash,started_at=now,last_activity_at=now)
  db.add(us);db.flush()
 us.last_activity_at=now
 if event_type=="user_message":us.user_messages=(us.user_messages or 0)+1
 elif event_type=="assistant_response":us.assistant_responses=(us.assistant_responses or 0)+1
 elif event_type=="response_completed":us.completed_responses=(us.completed_responses or 0)+1
 db.add(UsageEvent(session_id=sid,user_hash=user_hash,event_type=event_type,topic=topic,link_category=link_category,created_at=now))
 db.commit();db.close()
# Inactivity is measured from the last learner action, not from background polling.
INACTIVITY_MINUTES=10
TERMINATION_RE=re.compile(r"^(?:thank\s*you(?:\s+(?:so|very)\s+much)?|thanks(?:\s+a\s+lot)?|thx|asante(?:\s+sana)?|kwaheri|kwa\s+heri|goodbye|good\s+bye|bye(?:\s+bye)?|exit|quit|end(?:\s+(?:the|this|our|my))?\s+(?:chat|conversation|session)|stop(?:\s+chatting)?|that(?:'s| is)\s+all|no\s+more\s+questions|nimemaliza|tutaonana)[.!\s]*$",re.I)

def is_termination_message(text):
 return bool(TERMINATION_RE.fullmatch(text.strip()))

def start_learner_session():
 st.session_state["_history"]=[]
 st.session_state["_usage_session"]=uuid.uuid4().hex
 st.session_state["_session_closed"]=False
 st.session_state["_last_learner_activity"]=utc_now()
 usage_event("session_started")

def close_learner_session(reason):
 if st.session_state.get("_session_closed"):return
 sid=st.session_state.get("_usage_session")
 if sid:
  db=Session();rec=db.query(UsageSession).filter_by(session_id=sid).first()
  if rec:
   rec.ended_at=utc_now()
   db.add(UsageEvent(session_id=sid,user_hash=rec.user_hash,event_type="session_ended",topic=reason,created_at=utc_now()))
   db.commit()
  db.close()
 st.session_state["_session_closed"]=True

@st.fragment(run_every="30s")
def session_idle_watch():
 if st.session_state.get("_session_closed"):return
 last=st.session_state.get("_last_learner_activity")
 if last and utc_now()-last>=timedelta(minutes=INACTIVITY_MINUTES):
  close_learner_session("inactivity")
  st.info("Conversation ended automatically after 10 minutes without interaction. Send a new question to begin a new session.")
  st.rerun(scope="app")
RESOURCE_ROUTES={
 "SYMPTOMS":["testing","referral"],"TESTING":["testing"],"WINDOW_PERIOD":["testing"],
 "PREVENTION":["prevention"],"TRANSMISSION":["prevention"],"TREATMENT":["referral"],
 "MEDICATION":["referral"],"EXPOSURE_RISK":["testing","prevention"],
 "URGENT_HEALTH_CONCERN":["referral"],"PARTNER_NOTIFICATION":["testing","referral"],
 "GENERAL_INFORMATION":["prevention","testing"],"MISCONCEPTION":["prevention"]
}
RESOURCE_LINKS={
 "testing":("STI testing and health services","https://www.health.go.ke/"),
 "prevention":("WHO STI prevention and information","https://www.who.int/health-topics/sexually-transmitted-infections"),
 "referral":("Kenya Ministry of Health services","https://www.health.go.ke/")
}
def route_resources(intent,entities):
 categories=list(RESOURCE_ROUTES.get(str(intent).upper(),["testing","prevention"]))
 if entities.get("symptoms") and "testing" not in categories:categories.insert(0,"testing")
 return categories
def tracked_link(label,url,category,key):
 # Streamlit cannot reliably observe clicks on ordinary markdown links, so use a button that records then opens the service.
 if st.button(label,key=key):
  st.session_state["_last_learner_activity"]=utc_now()
  usage_event("service_link_click",link_category=category)
  st.markdown(f"[Open {label}]({url})")
def boot():
 Base.metadata.create_all(engine); s=Session()
 admin_user=secret_value("ADMIN_USERNAME"); admin_password=secret_value("ADMIN_PASSWORD")
 # Deployment Secrets are authoritative: synchronize the admin on each restart.
 if admin_user and admin_password:
  configured=s.query(User).filter_by(role="admin").order_by(User.id).first()
  if configured:
   configured.username=admin_user
   configured.password_hash=hash_password(admin_password)
   configured.active=True
  else:
   s.add(User(username=admin_user,password_hash=hash_password(admin_password),role="admin",active=True))
 with open(R/"data/content_seed.csv",encoding="utf8") as f:
  for x in csv.DictReader(f):
   exists=s.query(Content.id).filter_by(topic=x["topic"],language=x["language"],title=x["title"]).first()
   if not exists:s.add(Content(topic=x["topic"],language=x["language"],title=x["title"],body=x["body"],source=x["source"],version=x["version"],status="pending_review"))
 s.commit(); s.close()
@st.cache_resource
def model():
 try:return joblib.load(R/"models/intent_model.joblib")
 except:return None
def classify_inquiry(question,trained):
 t=question.lower()
 rules=[
  ("URGENT_HEALTH_CONCERN",["severe pain","high fever","fainting","emergency","urgent care","immediate medical","severe pelvic","severe testicular"]),
  ("MEDICATION",["medicine","medication","antibiotic","antibiotics","prescription","drug for","leftover antibiotics"]),
  ("TESTING",["get tested","get a test","testing center","testing centre","where can i test","what test","test detects","do i need testing","seek an sti test","should i test"]),
  ("WINDOW_PERIOD",["window period","too early to test","how soon after","how long should i wait","when is testing reliable","when will an sti show"]),
  ("PARTNER_NOTIFICATION",["tell my partner","inform a sexual partner","partner notification","recent partners","partner need testing"]),
  ("MISCONCEPTION",["toilet seat","only promiscuous","by looking at","are stis always","i heard"]),
  ("SYMPTOMS",["symptoms","signs of","burning when","pain when i pee","discharge","genital sores"]),
  ("TRANSMISSION",["transmitted","how can someone catch","how does it spread","spread during sex"]),
  ("PREVENTION",["prevent","prevention","reduce my sti risk","safer sex","protect myself","condoms help"]),
  ("TREATMENT",["treated","treatment","cured","positive sti test"]),
  ("EXPOSURE_RISK",["my sti risk","how risky","possible sti exposure","condom broke","unprotected sex"]),
 ]
 for label,phrases in rules:
  if any(x in t for x in phrases):return label
 return str(trained.predict([question])[0]) if trained else "GENERAL_INFORMATION"
def concern_key(question):
 t=question.casefold()
 patterns=[
  ("urine_colour",r"\b(yellow|dark|orange|brown|cloudy)\s+urine\b|\burine\s+(?:is|looks|turned)\s+(?:yellow|dark|orange|brown|cloudy)\b|mkojo\s+wa\s+njano"),
  ("painful_urination",r"\b(pain|painful|burn|burning|stinging|hurts?)\b.{0,35}\b(urina(?:te|ting|tion)|pee|peeing|pass(?:ing)?\s+urine)\b|\b(painful urination|dysuria)\b|maumivu\s+nikikojoa"),
  ("genital_itching",r"\b(itch|itchy|itching|scratchy)\b.{0,35}\b(private parts?|genitals?|vagina|vulva|penis|groin)\b|\b(private parts?|genitals?|vagina|vulva|penis|groin)\b.{0,35}\b(itch|itchy|itching)\b|kuwashwa\s+sehemu\s+za\s+siri"),
  ("genital_discharge",r"\b(discharge|fluid|pus)\b.{0,35}\b(penis|vagina|genital|private parts?)\b|\b(penis|vagina|genital)\b.{0,35}\b(discharge|fluid|pus)\b"),
  ("genital_sores",r"\b(sores?|blisters?|ulcers?)\b.{0,35}\b(genital|penis|vagina|private parts?)\b")]
 for key,pattern in patterns:
  if re.search(pattern,t):return key
 return None

def approved_response(db,language,intent,entities,concern=None):
 """Select only explicitly approved content, matching intent before disease/general."""
 disease=entities.get("topics",[])
 keys=[]
 if concern:keys.append("concern:"+concern)
 for topic in disease:keys.append(f"{topic}:{intent.lower()}")
 keys.append(f"intent:{intent.lower()}")
 for topic in disease:keys.append(topic)
 if not concern:keys.append("general")
 for key in keys:
  found=db.query(Content).filter_by(topic=key,language=language,status="approved").order_by(Content.id).all()
  if found:return found,key
 return [],None
def redact(t):
 t=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',"[email redacted]",t)
 return re.sub(r'(?<!\w)(?:\+?\d[\d\s\-()]{7,}\d)(?!\w)',"[phone/number redacted]",t)
def extract(t):
 """Conservative phrase matching: explicit mentions only, not diagnoses."""
 x=re.sub(r"\s+"," ",t.casefold()).strip()
 o={"topics":[],"symptoms":[],"durations":[],"exposures":[]}
 patterns={
  "topics":{
   "gonorrhoea":[r"\bgonorrh(?:oea|ea)\b",r"\bkisonono\b"],
   "chlamydia":[r"\bchlamydia\b"],"syphilis":[r"\bsyphilis\b",r"\bkaswende\b"],
   "hiv":[r"\bhiv\b",r"\bukimwi\b"],"herpes":[r"\bherpes\b"],
   "hpv":[r"\bhpv\b",r"\bhuman papilloma(?:virus)?\b"],
   "trichomoniasis":[r"\btrichomoniasis\b",r"\btrich\b"],
  },
  "symptoms":{
   "genital_itching":[r"\bitch(?:ing|y)?\b.{0,35}\b(?:private parts?|genitals?|vagina|vulva|penis|groin)\b",
                     r"\b(?:private parts?|genitals?|vagina|vulva|penis|groin)\b.{0,35}\bitch(?:ing|y)?\b",
                     r"\bkuwashwa\b",r"\bgenital itching\b"],
   "dysuria":[r"\b(?:pain|burn|burning|stinging|hurt|hurts)\b.{0,32}\b(?:pee|peeing|urinat(?:e|ing|ion)|pass(?:ing)? urine)\b",
              r"\b(?:painful urination|dysuria)\b",r"\bmaumivu nikikojoa\b",r"\bkuungua nikikojoa\b"],
   "genital_discharge":[r"\b(?:penile|vaginal|genital|abnormal|yellow|green) discharge\b",
                       r"\bdischarge\b.{0,25}\b(?:penis|vagina|genitals?)\b",r"\buchafu sehemu za siri\b"],
   "pelvic_pain":[r"\bpelvic pain\b",r"\blower (?:abdominal|belly) pain\b",r"\bmaumivu ya nyonga\b"],
   "testicular_pain":[r"\b(?:testicular pain|testicle pain|painful testicle|swollen testicle)\b",r"\bmaumivu ya korodani\b"],
   "genital_sores":[r"\b(?:genital sores?|genital ulcers?|sores? on (?:my )?(?:penis|vagina))\b",r"\bvidonda sehemu za siri\b"],
   "rash":[r"\b(?:rash|upele)\b"],"fever":[r"\b(?:fever|homa)\b"],
   "yellow_urine":[r"\b(?:yellow|dark yellow) urine\b",r"\burine is yellow\b",r"\bmkojo wa njano\b"]
  },
  "exposures":{
   "unprotected_sex":[r"\bunprotected sex\b",r"\bsex without (?:a )?condom\b",r"\bngono bila kondomu\b"],
   "oral_sex":[r"\boral sex\b",r"\bngono ya mdomo\b"],
   "new_partner":[r"\bnew (?:sexual )?partner\b",r"\bmwenza mpya\b"],
  }
 }
 for typ,entities in patterns.items():
  for label,regexes in entities.items():
   if any(re.search(rx,x) for rx in regexes):o[typ].append(label)
 o["durations"]=re.findall(r"\b\d+\s*(?:days?|weeks?|months?|siku|wiki|mwezi|miezi)\b",x)
 return o
@st.cache_resource
def entity_model():
 try:
  artifact=joblib.load(R/"models/entity_model.joblib")
  return artifact
 except Exception:
  return None

def extract_meaning(question):
 """ML multilabel prediction + transparent rule fallback; no diagnoses."""
 base=extract(question)
 artifact=entity_model()
 if artifact is not None:
  probabilities=artifact["pipeline"].predict_proba([question])[0]
  for label,score in zip(artifact["classes"],probabilities):
   if score < artifact["threshold"]:continue
   kind,value=label.split(":",1)
   if kind in ("topics","symptoms","exposures") and value not in base[kind]:
    base[kind].append(value)
 # Simple explicit negation guard for frequent symptom assertions.
 # Does not claim comprehensive negation handling.
 negations={
  "genital_itching":r"\b(?:no|without|not experiencing)\s+(?:genital\s+)?itch(?:ing|iness)?\b",
  "dysuria":r"\b(?:no|without)\s+(?:painful urination|pain when (?:i )?pee|burning urination)\b",
  "fever":r"\b(?:no|without)\s+fever\b",
 }
 text=question.casefold()
 for label,pattern in negations.items():
  if re.search(pattern,text) and label in base["symptoms"]:
   base["symptoms"].remove(label)
 return base
def log(s,a,act,typ,oid="",d=""):s.add(Audit(actor=a,action=act,object_type=typ,object_id=str(oid),details=d))
st.set_page_config(page_title="STI Information Assistant",page_icon="🩺",layout="wide"); boot()
st.title("STI Information Assistant"); st.caption("Educational/research prototype — not a diagnostic or prescribing system.")
mode=st.sidebar.radio("Open",["Learner assistant","Admin"])
if mode=="Learner assistant":
 lang=st.selectbox("Language / Lugha",[("English","en"),("Kiswahili","sw")],format_func=lambda z:z[0])[1]
 st.info("Do not enter identifying information. Symptoms alone cannot confirm an STI." if lang=="en" else "Usiweke taarifa zinazokutambulisha. Dalili pekee haziwezi kuthibitisha STI.")
 st.subheader("Basic information" if lang=="en" else "Taarifa za msingi")
 st.caption("These fields are used only for aggregate research reporting. Avoid entering a home address." if lang=="en" else "Taarifa hizi hutumika tu kwa ripoti za jumla za utafiti. Usiweke anwani ya nyumbani.")
 c1,c2=st.columns(2)
 with c1:
  gender=st.selectbox("Gender" if lang=="en" else "Jinsia",["Prefer not to say","Male","Female","Other"])
  age_bracket=st.selectbox("Age bracket" if lang=="en" else "Kundi la umri",["Prefer not to say","18-19 years","20-22 years","23-25 years"])
  sexually_active=st.selectbox("Sexually active?" if lang=="en" else "Je, unashiriki ngono?",["Prefer not to say","Yes","No"])
 with c2:
  residence=st.text_input("Residence (county/town only)" if lang=="en" else "Makazi (kaunti/mji pekee)",placeholder="e.g. Nairobi")
  nearest_health_facility=st.text_input("Nearest health facility" if lang=="en" else "Kituo cha afya kilicho karibu",placeholder="e.g. local clinic or hospital")
 demographic_consent=st.checkbox("I consent to storing these basic details in de-identified form for aggregate research reporting." if lang=="en" else "Ninakubali taarifa hizi za msingi zihifadhiwe bila utambulisho kwa ripoti za jumla za utafiti.")
 if "_usage_session" not in st.session_state or "_session_closed" not in st.session_state:
  start_learner_session()
 if not st.session_state["_session_closed"] and utc_now()-st.session_state["_last_learner_activity"]>=timedelta(minutes=INACTIVITY_MINUTES):
  close_learner_session("inactivity")
 session_idle_watch()
 if st.session_state["_session_closed"]:
  st.info("This conversation has ended. Your next question will automatically start a new session." if lang=="en" else "Mazungumzo haya yamekamilika. Swali linalofuata litaanza kikao kipya kiotomatiki.")
 with st.sidebar.expander("STI service links (optional)",expanded=False):
  st.caption("Opening a service link is counted separately from automated recommendations.")
  for category,(label,url) in RESOURCE_LINKS.items():
   if st.button(label,key=f"sidebar_service_{category}"):
    usage_event("service_link_click",link_category=category)
    st.markdown(f"[Open {label}]({url})")
 st.subheader("STI conversation" if lang=="en" else "Mazungumzo ya STI")
 # Render the conversation as one uninterrupted sequence of chat bubbles.
 for turn in st.session_state["_history"]:
  with st.chat_message(turn["role"]):
   st.markdown(turn["text"])
 consent=st.checkbox("I consent to storing a redacted copy for prototype evaluation." if lang=="en" else "Ninakubali nakala iliyofichwa taarifa binafsi ihifadhiwe kwa tathmini ya mfano huu.")
 # st.chat_input sends on Enter (Shift+Enter inserts a newline).
 q=st.chat_input("Type your STI question and press Enter…" if lang=="en" else "Andika swali lako la STI na ubonyeze Enter…")
 if q and q.strip():
  # An ended session never receives another question: create a new one first.
  if st.session_state.get("_session_closed"):
   start_learner_session()
  elif utc_now()-st.session_state["_last_learner_activity"]>=timedelta(minutes=INACTIVITY_MINUTES):
   close_learner_session("inactivity")
   start_learner_session()
  st.session_state["_last_learner_activity"]=utc_now()
  if is_termination_message(q):
   st.session_state["_history"].append({"role":"user","text":q})
   usage_event("user_message",topic="conversation_termination")
   st.session_state["_history"].append({"role":"assistant","text":"You're welcome. This conversation has ended. Send another question whenever you would like to start a new session." if lang=="en" else "Karibu. Mazungumzo haya yamekamilika. Uliza swali jingine ili kuanza kikao kipya.","resources":[]})
   usage_event("assistant_response",topic="conversation_termination")
   usage_event("response_completed",topic="conversation_termination")
   close_learner_session("termination_text")
   st.rerun()
  m=model(); intent=classify_inquiry(q,m); e=extract_meaning(q); concern=concern_key(q)
  if concern:intent="SYMPTOMS"
  detected_topic=e["topics"][0] if e["topics"] else intent.lower()
  st.session_state["_history"].append({"role":"user","text":q})
  usage_event("user_message",topic=detected_topic)
  usage_event("intent_detected",topic=intent)
  for value in e.get("topics",[]): usage_event("sti_topic_detected",topic=value)
  for value in e.get("symptoms",[]): usage_event("symptom_detected",topic=value)
  for value in e.get("exposures",[]): usage_event("exposure_detected",topic=value)
  for value in e.get("durations",[]): usage_event("duration_detected",topic=value)
  # NLP extraction is internal and reported only in aggregate to administrators.
  s=Session();items,matched_key=approved_response(s,lang,intent,e,concern)
  topic=e["topics"][0] if e["topics"] else intent.lower()
  reply="\n\n".join(f"**{c.title}**\n\n{c.body}" for c in items) if items else ("No reviewer-approved educational content is available yet." if lang=="en" else "Bado hakuna maudhui yaliyoidhinishwa.")
  if matched_key=="general":
   reply=("*General STI information; specific content is awaiting approval.*\n\n" if lang=="en" else "*Taarifa za jumla za STI; maudhui mahususi yanasubiri idhini.*\n\n")+reply
  if e["symptoms"]:
   reply+=("\n\n*Symptoms alone cannot confirm an STI. Seek professional assessment if concerned.*" if lang=="en" else "\n\n*Dalili pekee haziwezi kuthibitisha STI. Tafuta ushauri wa mhudumu wa afya.*")
  # Service recommendations are research events, not learner-facing chat text.
  for category in route_resources(intent,e):
   usage_event("resource_recommended",topic=category)
  if concern:
   usage_event("concern_detected",topic=concern)
  st.session_state["_history"].append({"role":"assistant","text":reply})
  usage_event("assistant_response",topic=topic);usage_event("response_completed",topic=topic)
  user_hash,session_id=usage_ids()
  if consent:s.add(Inquiry(session_hash=session_id,language=lang,intent=intent,entities_json=json.dumps(e),raw_text=redact(q),consent_to_store=True))
  if demographic_consent:
   s.add(DemographicProfile(session_hash=session_id,gender=gender,age_bracket=age_bracket,sexually_active=sexually_active,residence=redact(residence.strip())[:100],nearest_health_facility=redact(nearest_health_facility.strip())[:150],consent_to_store=True))
  s.commit();s.close()
  st.rerun()  # Render the new user/assistant pair in sequence in the chat area.
else:
 if not st.session_state.get("admin_ok"):
  configured_user=secret_value("ADMIN_USERNAME"); configured_password=secret_value("ADMIN_PASSWORD")
  if not configured_user or not configured_password:
   st.error("Admin login is not configured. Add ADMIN_USERNAME and ADMIN_PASSWORD in Streamlit App Settings > Secrets, save, then reboot the app.")
   st.stop()
  st.info("Use the ADMIN_USERNAME and ADMIN_PASSWORD currently configured in Streamlit Secrets.")
  u=st.text_input("Username"); p=st.text_input("Password",type="password")
  if st.button("Log in"):
   s=Session(); z=s.query(User).filter_by(username=u,active=True).first(); ok=z and verify_password(p,z.password_hash);s.close()
   if ok:st.session_state.admin_ok=True;st.session_state.admin_user=u;st.rerun()
   else:st.error("Invalid credentials.")
 else:
  actor=st.session_state.get("admin_user","admin"); st.success(f"Signed in as {actor}")
  if st.button("Log out"):st.session_state.admin_ok=False;st.rerun()
  t1,t2,t3,t4,t5,t6,t7,t8,t9=st.tabs(["Review content","Create content","Approved content","Participant reporting","Usage analytics","Audit log","Privacy / retention","Account","Mapping & validation"])
  with t1:
   s=Session(); pending=s.query(Content).filter_by(status="pending_review").order_by(Content.id).all()
   st.caption("Approval must be performed by an actual qualified reviewer. The application does not manufacture expert approval.")
   for c in pending:
    with st.expander(f"#{c.id} [{c.language}] {c.title}"):
     st.write(c.body);st.caption(f"{c.source} | v{c.version}");rv=st.text_input("Reviewer name / role",key=f"r{c.id}");a,b=st.columns(2)
     if a.button("Approve",key=f"a{c.id}"):
      if not rv.strip():st.error("Enter the real reviewer name/role.")
      else:c.status="approved";c.reviewer=rv.strip();c.reviewed_at=utc_now();c.updated_at=utc_now();log(s,actor,"approve","content",c.id,f"reviewer={rv.strip()}");s.commit();st.rerun()
     if b.button("Archive",key=f"x{c.id}"):c.status="archived";c.updated_at=utc_now();log(s,actor,"archive","content",c.id);s.commit();st.rerun()
   s.close()
  with t2:
   with st.form("new"):
    tp=st.text_input("Topic",value="general");la=st.selectbox("Language",["en","sw"]);ti=st.text_input("Title");bo=st.text_area("Body");so=st.text_input("Source");ve=st.text_input("Version",value="1.0")
    if st.form_submit_button("Save as pending review"):
     s=Session();c=Content(topic=tp,language=la,title=ti,body=bo,source=so,version=ve,status="pending_review");s.add(c);s.flush();log(s,actor,"create","content",c.id,"pending_review");s.commit();s.close();st.success("Saved as pending_review.")
  with t3:
   s=Session()
   for c in s.query(Content).filter_by(status="approved").all():st.markdown(f"**#{c.id} [{c.language}] {c.title}**");st.write(c.body);st.caption(f"Reviewer: {c.reviewer} | Source: {c.source}")
   s.close()
  with t4:
   st.subheader("Aggregate participant reporting")
   st.caption("Only grouped counts are shown. Individual demographic records and inquiry text are not displayed together.")
   s=Session(); rows=s.query(DemographicProfile).filter_by(consent_to_store=True).all()
   st.metric("Consenting demographic records",len(rows))
   def counts(field):
    out={}
    for r in rows:
     v=getattr(r,field) or "Not provided";out[v]=out.get(v,0)+1
    return [{"category":k,"count":v} for k,v in sorted(out.items(),key=lambda x:(-x[1],x[0]))]
   a,b=st.columns(2)
   with a:
    st.markdown("**Gender**");st.dataframe(counts("gender"),width="stretch",hide_index=True)
    st.markdown("**Sexual activity**");st.dataframe(counts("sexually_active"),width="stretch",hide_index=True)
    st.markdown("**Residence**");st.dataframe(counts("residence"),width="stretch",hide_index=True)
   with b:
    st.markdown("**Age bracket**");st.dataframe(counts("age_bracket"),width="stretch",hide_index=True)
    st.markdown("**Nearest health facility**");st.dataframe(counts("nearest_health_facility"),width="stretch",hide_index=True)
   s.close()
  with t5:
   st.subheader("Routine-use behavioral analytics")
   st.caption("Automatically recorded pseudonymous interaction metrics. No post-interaction questionnaire is required.")
   db=Session(); sessions=db.query(UsageSession).all(); events=db.query(UsageEvent).all()
   unique_users=len(set(x.user_hash for x in sessions)); session_count=len(sessions)
   total_messages=sum((x.user_messages or 0) for x in sessions)
   turns=sum(min(x.user_messages or 0,x.assistant_responses or 0) for x in sessions)
   durations=[max(0,((x.last_activity_at or x.started_at)-x.started_at).total_seconds()) for x in sessions]
   avg_duration=(sum(durations)/len(durations)) if durations else 0
   by_user={}
   for x in sessions:by_user[x.user_hash]=by_user.get(x.user_hash,0)+1
   return_users=sum(1 for n in by_user.values() if n>1)
   completed=sum((x.completed_responses or 0) for x in sessions)
   responses=sum((x.assistant_responses or 0) for x in sessions)
   completion_rate=(100*completed/responses) if responses else 0
   # A conservative operational proxy: sessions with a user message but no completed assistant response.
   dropoffs=sum(1 for x in sessions if (x.user_messages or 0)>0 and (x.completed_responses or 0)==0)
   c1,c2,c3,c4=st.columns(4)
   c1.metric("Unique users",unique_users);c2.metric("Sessions",session_count);c3.metric("User messages",total_messages);c4.metric("Conversation turns",turns)
   c5,c6,c7,c8=st.columns(4)
   c5.metric("Return users",return_users);c6.metric("Avg. session duration",f"{avg_duration:.1f} sec");c7.metric("Response completion",f"{completion_rate:.1f}%");c8.metric("Conversation drop-off",dropoffs)
   st.markdown("**Frequency of return visits**")
   st.dataframe([{"sessions_per_user":n,"users":sum(1 for v in by_user.values() if v==n)} for n in sorted(set(by_user.values()))],width="stretch",hide_index=True)
   def event_counts(kind):
    out={}
    for e in events:
     if e.event_type==kind and e.topic:out[e.topic]=out.get(e.topic,0)+1
    return out
   intents=event_counts("intent_detected");sti_topics=event_counts("sti_topic_detected")
   symptoms=event_counts("symptom_detected");exposures=event_counts("exposure_detected");durations=event_counts("duration_detected")
   requested={};links={"testing":0,"prevention":0,"referral":0}
   for e in events:
    if e.event_type=="user_message" and e.topic:requested[e.topic]=requested.get(e.topic,0)+1
    if e.event_type=="service_link_click" and e.link_category:links[e.link_category]=links.get(e.link_category,0)+1
   def rows(data,label):return [{label:k,"count":v} for k,v in sorted(data.items(),key=lambda x:(-x[1],x[0]))]
   st.markdown("### Aggregated NLP information")
   a,b=st.columns(2)
   with a:
    st.markdown("**Inquiry intents**");st.dataframe(rows(intents,"intent"),width="stretch",hide_index=True)
    st.markdown("**STI topics explicitly mentioned**");st.dataframe(rows(sti_topics,"STI topic"),width="stretch",hide_index=True)
    st.markdown("**Symptoms mentioned**");st.dataframe(rows(symptoms,"symptom"),width="stretch",hide_index=True)
   with b:
    st.markdown("**Exposure indicators mentioned**");st.dataframe(rows(exposures,"exposure"),width="stretch",hide_index=True)
    st.markdown("**Durations mentioned**");st.dataframe(rows(durations,"duration"),width="stretch",hide_index=True)
    st.markdown("**Frequently requested information**");st.dataframe(rows(requested,"topic / intent"),width="stretch",hide_index=True)
   st.markdown("**Recommended STI resource categories**")
   st.dataframe(rows(event_counts("resource_recommended"),"resource category"),width="stretch",hide_index=True)
   st.markdown("**Specific concerns detected**")
   st.dataframe(rows(event_counts("concern_detected"),"concern"),width="stretch",hide_index=True)
   st.markdown("**Service-link interactions (actual clicks)**")
   st.dataframe([{"service":k,"clicks":v} for k,v in links.items()],width="stretch",hide_index=True)
   st.caption("STI topics count only explicitly named infections (e.g., gonorrhoea), not broad symptom questions. Symptom counts require matched wording; unmatched questions do not imply symptoms are absent. Resource recommendations are separate from actual service-link clicks.")
   st.caption("Drop-off is an operational proxy, not a clinical outcome. Session duration is measured from first to last recorded activity.")
   db.close()
  with st.expander("STI inquiry signal maps, trends and technical discrepancy report",expanded=False):
   st.warning("These are **chatbot inquiry mentions**, NOT measured STI prevalence, confirmed cases or outbreak alerts. Do not use these results to diagnose or declare an outbreak. Confirmed epidemiological reporting requires verified case counts, population denominators, surveillance coverage and public-health review.")
   import pandas as pd
   # Only join records where both inquiry and demographic storage were explicitly consented.
   review_db=Session()
   inquiries=review_db.query(Inquiry).filter_by(consent_to_store=True).all()
   profiles=review_db.query(DemographicProfile).filter_by(consent_to_store=True).order_by(DemographicProfile.created_at.desc()).all()
   profile_by_session={}
   for profile in profiles:
    profile_by_session.setdefault(profile.session_hash,profile)
   # Approximate county centroids, not users' physical positions.
   county_coords={
    "nairobi":(-1.2864,36.8172),"mombasa":(-4.0435,39.6682),"kisumu":(-0.0917,34.7680),
    "nakuru":(-0.3031,36.0800),"kiambu":(-1.1714,36.8356),"machakos":(-1.5177,37.2634),
    "kajiado":(-1.8524,36.7768),"uasin gishu":(0.5143,35.2698),"kakamega":(0.2827,34.7519),
    "kilifi":(-3.6305,39.8499),"kwale":(-4.1741,39.4521),"busia":(0.4608,34.1115),
    "bungoma":(0.5635,34.5606),"meru":(0.0463,37.6559),"embu":(-0.5388,37.4596),
    "nyeri":(-0.4201,36.9476),"kirinyaga":(-0.6591,37.3827),"murang'a":(-0.7210,37.1526),
    "nyandarua":(-0.1833,36.4667),"laikipia":(0.3606,36.7820),"narok":(-1.0783,35.8711),
    "kericho":(-0.3677,35.2831),"bomet":(-0.7813,35.3416),"nandi":(0.1833,35.1167),
    "trans nzoia":(1.0567,34.9507),"siaya":(0.0612,34.2882),"homa bay":(-0.5273,34.4571),
    "migori":(-1.0634,34.4731),"kisii":(-0.6817,34.7667),"nyamira":(-0.5633,34.9358),
    "vihiga":(0.0743,34.7220),"turkana":(3.1167,35.6000),"west pokot":(1.6219,35.2167),
    "samburu":(1.2155,36.9541),"isiolo":(0.3556,37.5833),"marsabit":(2.3284,37.9899),
    "mandera":(3.9373,41.8569),"wajir":(1.7471,40.0573),"garissa":(-0.4532,39.6461),
    "tana river":(-1.5264,40.0193),"lamu":(-2.2717,40.9020),"taita taveta":(-3.3964,38.5561),
    "kitui":(-1.3667,38.0167),"makueni":(-1.8041,37.6203),"tharaka nithi":(-0.2960,37.9030),
    "baringo":(0.4700,35.9700),"elgeyo marakwet":(0.9500,35.5100),"kapenguria":(1.2389,35.1119)
   }
   def normalize_county(raw):
    value=(raw or "").casefold().strip()
    value=re.sub(r"\b(county|kaunti)\b","",value).strip()
    # Do not guess a county from a free-text town or address.
    return value if value in county_coords else None
   observed=[];unmatched=0;malformed=0;disagreement=0;missing_profile=0
   for inquiry in inquiries:
    try:
     entities=json.loads(inquiry.entities_json or "{}")
     if not isinstance(entities,dict):raise ValueError("invalid entities")
    except (ValueError,TypeError):
     malformed+=1;continue
    topics=entities.get("topics",[]);symptoms=entities.get("symptoms",[])
    if not isinstance(topics,list) or not isinstance(symptoms,list):malformed+=1;continue
    profile=profile_by_session.get(inquiry.session_hash)
    if profile is None:missing_profile+=1
    county=normalize_county(profile.residence) if profile else None
    if profile and not county:unmatched+=1
    # Diagnostic disagreement is not ground-truth error: it flags records for manual QA.
    if inquiry.raw_text:
     rule=extract(inquiry.raw_text)
     if set(rule.get("topics",[]))!=set(topics) or set(rule.get("symptoms",[]))!=set(symptoms):
      disagreement+=1
    observed.append({"day":inquiry.created_at.date() if inquiry.created_at else None,
                     "session":inquiry.session_hash,"county":county,"topics":list(set(topics)),
                     "symptoms":list(set(symptoms))})
   review_db.close()
   st.caption("Location is an optional self-reported county, mapped to its approximate centroid. County data are shown only for groups with at least five distinct consented sessions; towns, unknown counties and small groups are suppressed.")
   a,b,c,d=st.columns(4)
   a.metric("Consented inquiries",len(inquiries));b.metric("Malformed extraction records",malformed)
   c.metric("Extractor disagreements",disagreement);d.metric("Unmatched / missing county",unmatched+missing_profile)
   st.caption("Extractor disagreement means ML+rules and rules-only outputs differ; it does not prove either is incorrect. Repeated demographic profiles are deduplicated by session.")
   if observed:
    day_counts={}
    for rec in observed:
     if rec["day"]:day_counts[rec["day"]]=day_counts.get(rec["day"],0)+1
    if day_counts:
     st.markdown("**Daily consented inquiry volume (not case incidence)**")
     st.line_chart(pd.DataFrame([{"date":str(k),"inquiries":v} for k,v in sorted(day_counts.items())]).set_index("date"))
    topic_rows=[]
    for rec in observed:
     for topic in rec["topics"]:topic_rows.append({"topic":topic,"session":rec["session"]})
    if topic_rows:
     tdf=pd.DataFrame(topic_rows).drop_duplicates()
     st.markdown("**Sessions mentioning named STIs (not diagnosed infections)**")
     st.bar_chart(tdf.groupby("topic")["session"].nunique())
    groups={}
    for rec in observed:
     if rec["county"]:groups.setdefault(rec["county"],set()).add(rec["session"])
    eligible={county:len(sids) for county,sids in groups.items() if len(sids)>=5}
    if eligible:
     st.markdown("**Geographic distribution of consenting chatbot sessions (county centroid)**")
     map_df=pd.DataFrame([{"county":county.title(),"lat":county_coords[county][0],"lon":county_coords[county][1],"sessions":count} for county,count in sorted(eligible.items())])
     st.map(map_df,latitude="lat",longitude="lon",size="sessions")
     st.dataframe(map_df[["county","sessions"]],width="stretch",hide_index=True)
    else:st.info("No county meets the minimum five-session privacy threshold yet. The geographic map is suppressed.")
    st.markdown("**Potential technical discrepancies and limitations**")
    st.dataframe(pd.DataFrame([
     {"check":"Malformed entity JSON / types","records":malformed,"interpretation":"Unable to interpret stored extraction"},
     {"check":"ML/rule disagreement","records":disagreement,"interpretation":"Manual label review needed; not confirmed error"},
     {"check":"Unrecognized self-reported county","records":unmatched,"interpretation":"Location cannot be mapped reliably"},
     {"check":"No consented demographic record","records":missing_profile,"interpretation":"Not eligible for geographic breakdown"}
    ]),width="stretch",hide_index=True)
    st.download_button("Download aggregate data-quality report (CSV)",data=pd.DataFrame([
     {"check":"malformed_extractions","count":malformed},{"check":"extractor_disagreements","count":disagreement},
     {"check":"unmatched_county","count":unmatched},{"check":"missing_consenting_profile","count":missing_profile}
    ]).to_csv(index=False),file_name="sti_inquiry_quality_summary.csv",mime="text/csv")
   else:st.info("No consented inquiry records available. Ask test questions with explicit consent to populate this dashboard.")
   st.info("**Outbreak reporting:** No outbreak can be established from these data. If an unusual inquiry trend is observed, report it as an unverified information-seeking signal for manual investigation, not a public-health alert.")
  with st.expander("Inspect NLP algorithms: supervised multi-label ML vs rule-based extractor",expanded=False):
   st.markdown("### Compare the two information-extraction approaches")
   st.caption("Administrator-only, on-demand demonstration. Text entered here is not saved, logged or used for training. Avoid personal information.")
   st.markdown("**Supervised ML:** character n-gram TF-IDF + One-vs-Rest logistic regression. **Rules:** explicit phrase/regex matching. The combined output is used for learner inquiry analytics; it is not a diagnosis.")
   demo=st.text_area("Example inquiry (English or Kiswahili)",value="I have pain while urinating after unprotected sex. Could it be gonorrhoea?",height=90,key="ml_rules_demo")
   if st.button("Compare extraction methods",key="run_ml_rules_demo"):
    import pandas as pd
    if not demo.strip():st.warning("Enter a sample question.")
    elif len(demo)>1000:st.warning("Keep the example under 1,000 characters.")
    else:
     rules=extract(demo)
     artifact=entity_model()
     if artifact is None:
      st.error("The ML model could not be loaded. Check models/entity_model.joblib and dependencies.")
     else:
      try:
       probabilities=artifact["pipeline"].predict_proba([demo])[0]
       threshold=float(artifact["threshold"])
       predicted={"topics":[],"symptoms":[],"exposures":[],"durations":[]}
       scored=[]
       for label,score in zip(artifact["classes"],probabilities):
        kind,value=label.split(":",1)
        if kind in predicted and score>=threshold:predicted[kind].append(value)
        scored.append({"label":label,"model_probability":round(float(score),3),"selected":bool(score>=threshold)})
       combined=extract_meaning(demo)
       left,right=st.columns(2)
       with left:
        st.markdown("**Supervised multi-label ML**")
        st.json(predicted)
        st.caption(f"Decision threshold: {threshold:.2f}. Probabilities are model scores, not clinical probabilities.")
       with right:
        st.markdown("**Rule-based extraction**")
        st.json(rules)
        st.caption("Rules match explicit terms and durations. They may miss paraphrases.")
       st.markdown("**Combined extraction used by V17**")
       st.json(combined)
       comparison=[]
       for kind in ("topics","symptoms","exposures","durations"):
        for label in sorted(set(predicted[kind])|set(rules[kind])):
         comparison.append({"category":kind,"label":label,"ML":label in predicted[kind],"rules":label in rules[kind],"disagreement":(label in predicted[kind])!=(label in rules[kind])})
       if comparison:
        st.dataframe(pd.DataFrame(comparison),width="stretch",hide_index=True)
       else:st.info("Neither extractor detected an entity in this example.")
       with st.expander("Show all ML label probabilities"):
        st.dataframe(pd.DataFrame(sorted(scored,key=lambda x:-x["model_probability"])),width="stretch",hide_index=True)
       st.warning("Extractor disagreement is not automatically a technical error. Both systems can be wrong, especially on negation, hypothetical statements, or unfamiliar phrasing. This synthetic-trained model has not been independently clinically validated.")
      except Exception as err:st.error(f"Could not run comparison: {type(err).__name__}")
  with t9:
   from mapping_ui import render_mapping
   render_mapping(observed,county_coords,R)
  with t6:
   s=Session();st.dataframe([{"time":x.created_at,"actor":x.actor,"action":x.action,"object":f"{x.object_type}:{x.object_id}","details":x.details} for x in s.query(Audit).order_by(Audit.id.desc()).limit(200)],width="stretch");s.close()
  with t7:
   days=st.number_input("Delete stored inquiries older than N days",1,3650,90)
   if st.button("Run retention cleanup"):
    s=Session();cutoff=utc_now()-timedelta(days=int(days));n=s.query(Inquiry).filter(Inquiry.created_at<cutoff).delete();d=s.query(DemographicProfile).filter(DemographicProfile.created_at<cutoff).delete();ev=s.query(UsageEvent).filter(UsageEvent.created_at<cutoff).delete();us=s.query(UsageSession).filter(UsageSession.started_at<cutoff).delete();log(s,actor,"retention_cleanup","research_data","",f"inquiries={n}; demographics={d}; usage_events={ev}; usage_sessions={us}");s.commit();s.close();st.success(f"Deleted {n} inquiries, {d} demographic records, {ev} usage events and {us} usage sessions.")
  with t8:
   old=st.text_input("Current password",type="password");new=st.text_input("New password",type="password")
   if st.button("Change password"):
    s=Session();u=s.query(User).filter_by(username=actor).first()
    if not u or not verify_password(old,u.password_hash):st.error("Current password is incorrect.")
    elif len(new)<12:st.error("Use at least 12 characters.")
    else:u.password_hash=hash_password(new);log(s,actor,"password_change","user",u.id);s.commit();st.success("Password changed.")
    s.close()
