KHIDKI MAN — FULL FLASK WEBSITE + ADMIN PANEL
============================================

FEATURES
--------
Public website:
- Responsive marketing homepage with hero section, service cards, project portfolio,
  benefits, why-choose-us, process steps, FAQ and strong enquiry calls-to-action.
- Separate About Us, Services, Projects, Testimonials & Reviews, Enquiry, and Contact Us pages.
- Customer review submission form; reviews remain pending until an admin approves them.
- Admin can publish authentic older customer reviews (only with permission), approve/hide submissions, or delete them.
- Floating WhatsApp contact link, office information, phone/email and social links.
- SEO description and mobile-responsive styling.
- Public registration creates CUSTOMER accounts only. There is no public admin signup.

Protected admin panel:
- Enquiries inbox, status changes, call/WhatsApp links and date-wise CSV export.
- Add/remove services and projects.
- Create additional admin accounts from the protected admin panel only.
- Cannot delete your own admin account or the last remaining admin.
- Admin profile page lets the signed-in admin update their own name/email after current-password verification.
- Password change requires current password and a new password of at least 12 characters.
- Business settings can update company name, tagline, homepage marketing copy, CTA text, SEO description,
  phone, WhatsApp, email, GSTIN, office address, office hours, service areas, map link and social URLs.
- Business settings are rendered on the public site/contact/footer so updates do not require editing templates.

SETUP ON WINDOWS
----------------
1. Install Python 3.11 or 3.12 (recommended for compatibility).
2. Extract the ZIP and open the project folder in VS Code.
3. Open Terminal in the project folder and run:

   py -m venv .venv
   .venv\Scripts\activate
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   
4. Edit .env and replace SECRET_KEY with a long random secret. Add verified company contact details.
5. Create database tables and sample services:

   flask --app app init-db

6. Create the first admin (only for initial setup):

   flask --app app create-admin

   Follow the prompts and use a strong unique password. After this, create any additional admins
   from the signed-in admin panel; never expose a public admin registration route.

7. Start the website:

   python app.py

8. Open http://127.0.0.1:5000 in your browser.
   Admin login: http://127.0.0.1:5000/login

ADMIN MENU
----------
- /admin : enquiries, services, projects, admin accounts, review moderation
- /admin/profile : your own name/email and password security
- /admin/settings : business, office and marketing details

IMPORTANT SECURITY NOTES
------------------------
- Replace the development SECRET_KEY before deployment.
- Never commit .env, database files or real customer enquiry data to a public Git repository.
- For production, set DEBUG off, use HTTPS, configure a production WSGI server, back up the database,
  and use a managed database with access controls.
- Only publish verified contact details, GSTIN, service coverage, portfolio images and business claims.
- A full live deployment/integration test could not be run in this build environment because Flask
  dependencies are not installed here. Python syntax compilation passed; install requirements and
  test locally before publishing.
