from pathlib import Path
import json,pandas as pd,joblib
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,f1_score,classification_report,confusion_matrix
R=Path(__file__).resolve().parent
df=pd.read_csv(R/"data/intent_training.csv").dropna().drop_duplicates()
X1,X2,y1,y2=train_test_split(df.text,df.intent,test_size=.25,random_state=42,stratify=df.intent)
m=Pipeline([("tfidf",TfidfVectorizer(ngram_range=(1,2),sublinear_tf=True)),("clf",LogisticRegression(max_iter=1500,class_weight="balanced"))])
m.fit(X1,y1); p=m.predict(X2); joblib.dump(m,R/"models/intent_model.joblib")
metrics={"accuracy":accuracy_score(y2,p),"macro_f1":f1_score(y2,p,average="macro"),"weighted_f1":f1_score(y2,p,average="weighted"),"n_training":len(X1),"n_test":len(X2),"classes":sorted(df.intent.unique()),"classification_report":classification_report(y2,p,output_dict=True,zero_division=0),"warning":"Small demo dataset: metrics verify the prototype pipeline and are not research-grade validation."}
(R/"evaluation/metrics.json").write_text(json.dumps(metrics,indent=2))
labels=sorted(df.intent.unique()); pd.DataFrame(confusion_matrix(y2,p,labels=labels),index=labels,columns=labels).to_csv(R/"evaluation/confusion_matrix.csv")
