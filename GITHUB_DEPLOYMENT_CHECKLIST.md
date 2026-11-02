# Deployment checklist
1. Create a GitHub repository and upload the contents of this folder to its root.
2. Confirm `app.py` and `requirements.txt` are present.
3. Confirm `sti_app.db` and `.streamlit/secrets.toml` are NOT committed.
4. Connect the repository to Streamlit Community Cloud and use `app.py` as the entrypoint.
5. In the deployed app's Settings > Secrets add:
```toml
ADMIN_USERNAME = "your-admin-name"
ADMIN_PASSWORD = "your-long-unique-password"
```
6. Deploy/reboot, then choose Admin in the sidebar.
7. Only a real qualified reviewer should approve health content.
8. SQLite on hosted Streamlit should not be treated as durable production storage.
