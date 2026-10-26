
import csv
import io
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from functools import wraps

import click
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

# --------------------------------------------------
# ENVIRONMENT & APPLICATION CONFIGURATION
# --------------------------------------------------

load_dotenv()

app = Flask(__name__, instance_relative_config=True)
os.makedirs(app.instance_path, exist_ok=True)

IS_PRODUCTION = (
    os.getenv("RENDER") is not None
    or os.getenv("FLASK_ENV", "").lower() == "production"
)

secret_key = os.getenv("SECRET_KEY")

if IS_PRODUCTION and not secret_key:
    raise RuntimeError(
        "SECRET_KEY is required in production. "
        "Set it in your hosting provider's environment variables."
    )

app.config["SECRET_KEY"] = secret_key or "dev-only-secret-change-before-deployment"
app.config["DEBUG"] = (
    not IS_PRODUCTION and os.getenv("FLASK_DEBUG", "0") == "1"
)

database_url = os.getenv("DATABASE_URL", "sqlite:///company.db").strip()

# Some hosting providers supply postgres:// URLs.
# SQLAlchemy expects postgresql:// for PostgreSQL connections.
if database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://", "postgresql://", 1
    )

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
}

app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

UPLOAD_FOLDER = os.path.join(
    app.root_path, "static", "uploads", "projects"
)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

db = SQLAlchemy(app)
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def utc_now():
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def allowed_file(filename):
    """Check the uploaded file extension."""
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def process_and_save_image(file_storage, target_folder):
    """
    Validate, resize, and convert an uploaded image to WebP.
    Returns the relative static path, not a full URL.
    """
    os.makedirs(target_folder, exist_ok=True)

    filename = f"proj_{uuid.uuid4().hex}.webp"
    save_path = os.path.join(target_folder, filename)

    try:
        file_storage.stream.seek(0)

        with Image.open(file_storage.stream) as original:
            # Only accept actual supported image formats.
            if original.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Unsupported image content.")

            # Protect against excessively large decompressed images.
            original.load()
            image = ImageOps.exif_transpose(original)

            # Preserve transparency on a white background.
            if image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba_image = image.convert("RGBA")
                background = Image.new(
                    "RGBA", rgba_image.size, (255, 255, 255, 255)
                )
                background.alpha_composite(rgba_image)
                image = background.convert("RGB")
            else:
                image = image.convert("RGB")

            image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
            image.save(
                save_path,
                format="WEBP",
                quality=82,
                optimize=True,
            )

    except (UnidentifiedImageError, OSError) as exc:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise ValueError("The uploaded file is not a valid image.") from exc
    except Exception:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise

    return f"uploads/projects/{filename}"


def safe_commit():
    """Commit database changes and roll back if an error occurs."""
    try:
        db.session.commit()
        return True
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Database transaction failed.")
        return False


def get_settings():
    settings = DEFAULT_SETTINGS.copy()

    for row in Setting.query.all():
        settings[row.key] = row.value

    return settings


def admin_required(view):
    """Allow access only to authenticated administrators."""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


# --------------------------------------------------
# DEFAULT WEBSITE SETTINGS
# --------------------------------------------------

DEFAULT_SETTINGS = {
    "company_name": os.getenv("COMPANY_NAME", "THE KHIDKI MAN"),
    "tagline": os.getenv(
        "COMPANY_TAGLINE", "Window Services & Solutions"
    ),
    "phone": os.getenv("COMPANY_PHONE", "9649874351"),
    "whatsapp": os.getenv("COMPANY_WHATSAPP", "919649874351"),
    "email": os.getenv(
        "COMPANY_EMAIL", "Thekhidkiman@gmail.com"
    ),
    "address": os.getenv(
        "COMPANY_ADDRESS",
        "Flat No.: 09/264, RHB Colony: Aravali Vihar, "
        "Bhiwadi-301019, Khairthal - Tijara (Raj.)",
    ),
    "gst": os.getenv("COMPANY_GST", "08BHBPB6754K1Z8"),
    "contact_person": os.getenv(
        "COMPANY_CONTACT_PERSON", "Kamlesh Yadav"
    ),
    "hero_title": (
        "YOUR ONE-STOP DESTINATION FOR WINDOWS & DOORS SOLUTIONS!"
    ),
    "hero_description": (
        "Specialized uPVC, Aluminium, Slim Line & Partition "
        "installation services."
    ),
    "primary_cta": "Enquire Now",
    "office_hours": "Mon–Sat · 9:00 AM–7:00 PM",
    "service_area": "Bhiwadi, Khairthal, Tijara, NCR & nearby areas",
    "map_url": "",
    "instagram": "https://instagram.com/",
    "linkedin": "https://linkedin.com/",
    "facebook": "https://facebook.com/",
    "youtube": "https://youtube.com/",
    "why_us": (
        "Clear guidance, careful measurements, quality-focused "
        "solutions and responsive after-sales support."
    ),
    "promotion": (
        "Planning a new home or renovation? Tell us your requirements "
        "and request a personalised quotation."
    ),
    "meta_description": (
        "Explore window, door and installation solutions "
        "from The Khidki Man."
    ),
}


# --------------------------------------------------
# DATABASE MODELS
# --------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(
        db.String(160), unique=True, nullable=False, index=True
    )
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.String(20), nullable=False, default="customer"
    )
    created_at = db.Column(db.DateTime, default=utc_now)

    inquiries = db.relationship(
        "Inquiry", backref="customer", lazy=True
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price_label = db.Column(
        db.String(100), default="Contact for quotation"
    )
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    location = db.Column(db.String(140), default="")
    description = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=utc_now)


class Inquiry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    email = db.Column(db.String(160), default="")
    city = db.Column(db.String(100), default="")
    service = db.Column(db.String(140), default="")
    message = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.String(30), default="New", nullable=False
    )
    admin_notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utc_now)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=True
    )


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(120), default="")
    rating = db.Column(db.Integer, nullable=False, default=5)
    message = db.Column(db.Text, nullable=False)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=utc_now)


class Setting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, default="")


# --------------------------------------------------
# LOGIN & TEMPLATE HELPERS
# --------------------------------------------------

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@app.context_processor
def inject_globals():
    return {
        "company": get_settings(),
        "current_year": datetime.now().year,
    }


@app.template_filter("wa_link")
def wa_link(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return f"https://wa.me/{digits}" if digits else "#"


# --------------------------------------------------
# PUBLIC ROUTES
# --------------------------------------------------

@app.route("/")
def index():
    services = (
        Service.query.filter_by(active=True)
        .order_by(Service.created_at.desc())
        .all()
    )
    projects = (
        Project.query.order_by(Project.created_at.desc())
        .limit(6)
        .all()
    )
    reviews = (
        Review.query.filter_by(approved=True)
        .order_by(Review.created_at.desc())
        .limit(3)
        .all()
    )

    return render_template(
        "index.html",
        services=services,
        projects=projects,
        reviews=reviews,
    )


@app.route("/services")
def services_page():
    services = (
        Service.query.filter_by(active=True)
        .order_by(Service.created_at.desc())
        .all()
    )
    return render_template("services.html", services=services)


@app.route("/projects")
def projects_page():
    projects = (
        Project.query.order_by(Project.created_at.desc()).all()
    )
    return render_template("projects.html", projects=projects)


@app.route("/about")
def about_page():
    return render_template("about.html")


@app.route("/contact")
def contact_page():
    return render_template("contact_us.html")


@app.route("/reviews", methods=["GET", "POST"])
def reviews_page():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        location = request.form.get("location", "").strip()
        message = request.form.get("message", "").strip()

        try:
            rating = int(request.form.get("rating", "5"))
        except (TypeError, ValueError):
            rating = 0

        if not name or not message or rating not in range(1, 6):
            flash(
                "Please provide your name, valid rating (1-5), "
                "and review message.",
                "error",
            )
        else:
            review = Review(
                name=name,
                location=location,
                rating=rating,
                message=message,
                approved=False,
            )
            db.session.add(review)

            if safe_commit():
                flash(
                    "Thank you! Review moderation ke baad live hoga.",
                    "success",
                )
                return redirect(url_for("reviews_page"))

            flash("Review save nahi ho saka. Please try again.", "error")

    reviews = (
        Review.query.filter_by(approved=True)
        .order_by(Review.created_at.desc())
        .all()
    )
    return render_template("reviews.html", reviews=reviews)


@app.route("/enquiry", methods=["GET", "POST"])
def enquiry_page():
    services = (
        Service.query.filter_by(active=True)
        .order_by(Service.name)
        .all()
    )

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        city = request.form.get("city", "").strip()
        service = request.form.get("service", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not phone or not message:
            flash(
                "Name, phone number aur project details required hain.",
                "error",
            )
        else:
            inquiry = Inquiry(
                name=name,
                phone=phone,
                email=email,
                city=city,
                service=service,
                message=message,
                user_id=(
                    current_user.id
                    if current_user.is_authenticated
                    else None
                ),
            )
            db.session.add(inquiry)

            if safe_commit():
                flash(
                    "Enquiry submit ho gayi! Hamari team aapse contact karegi.",
                    "success",
                )
                return redirect(url_for("enquiry_page"))

            flash("Enquiry save nahi ho saki. Please try again.", "error")

    return render_template("contact.html", services=services)


# --------------------------------------------------
# CUSTOMER AUTHENTICATION
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("Saare required fields bharein.", "error")
        elif len(password) < 8:
            flash(
                "Password kam se kam 8 characters ka hona chahiye.",
                "error",
            )
        elif password != confirm:
            flash("Passwords match nahi karte.", "error")
        elif User.query.filter_by(email=email).first():
            flash("Ye email pehle se registered hai.", "error")
        else:
            user = User(name=name, email=email, role="customer")
            user.set_password(password)
            db.session.add(user)

            if safe_commit():
                login_user(user)
                flash("Account registered successfully.", "success")
                return redirect(url_for("dashboard"))

            flash("Registration fail ho gaya. Please try again.", "error")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))

        flash("Email ya password galat hai.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Aap sign out ho gaye.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    endpoint = (
        "admin_dashboard"
        if current_user.role == "admin"
        else "customer_dashboard"
    )
    return redirect(url_for(endpoint))


@app.route("/customer/dashboard")
@login_required
def customer_dashboard():
    if current_user.role == "admin":
        return redirect(url_for("admin_dashboard"))

    inquiries = (
        Inquiry.query.filter_by(user_id=current_user.id)
        .order_by(Inquiry.created_at.desc())
        .all()
    )
    return render_template(
        "customer_dashboard.html", inquiries=inquiries
    )


# --------------------------------------------------
# ADMIN DASHBOARD
# --------------------------------------------------

@app.route("/admin")
@admin_required
def admin_dashboard():
    search_query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()

    inquiry_query = Inquiry.query

    if search_query:
        like_pattern = f"%{search_query}%"
        inquiry_query = inquiry_query.filter(
            or_(
                Inquiry.name.ilike(like_pattern),
                Inquiry.phone.ilike(like_pattern),
                Inquiry.city.ilike(like_pattern),
                Inquiry.service.ilike(like_pattern),
            )
        )

    allowed_statuses = {
        "New", "Contacted", "Accepted", "Rejected", "Completed"
    }
    if status_filter in allowed_statuses:
        inquiry_query = inquiry_query.filter(
            Inquiry.status == status_filter
        )
    elif status_filter:
        status_filter = ""

    inquiries = (
        inquiry_query.order_by(Inquiry.created_at.desc()).all()
    )
    services = (
        Service.query.order_by(Service.created_at.desc()).all()
    )
    projects = (
        Project.query.order_by(Project.created_at.desc()).all()
    )
    admins = (
        User.query.filter_by(role="admin")
        .order_by(User.created_at.asc())
        .all()
    )
    reviews = (
        Review.query.order_by(Review.created_at.desc()).all()
    )

    stats = {
        "total": Inquiry.query.count(),
        "new": Inquiry.query.filter_by(status="New").count(),
        "contacted": Inquiry.query.filter_by(status="Contacted").count(),
        "accepted": Inquiry.query.filter_by(status="Accepted").count(),
        "completed": Inquiry.query.filter_by(status="Completed").count(),
        "services": Service.query.count(),
        "projects": Project.query.count(),
    }

    return render_template(
        "admin_dashboard.html",
        inquiries=inquiries,
        services=services,
        projects=projects,
        admins=admins,
        reviews=reviews,
        stats=stats,
        current_search=search_query,
        current_status=status_filter,
    )


# --------------------------------------------------
# ADMIN PROJECT MANAGEMENT
# --------------------------------------------------

@app.route("/admin/projects/add", methods=["POST"])
@admin_required
def add_project():
    title = request.form.get("title", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    image_file = request.files.get("project_image")

    if not title or not description:
        flash(
            "Project title aur description mandatory hain.", "error"
        )
        return redirect(url_for("admin_dashboard") + "#projects-admin")

    image_url = ""

    if image_file and image_file.filename:
        if not allowed_file(image_file.filename):
            flash(
                "Invalid image format! Only JPG, PNG, WEBP allowed.",
                "error",
            )
            return redirect(
                url_for("admin_dashboard") + "#projects-admin"
            )

        try:
            relative_path = process_and_save_image(
                image_file, app.config["UPLOAD_FOLDER"]
            )
            image_url = url_for("static", filename=relative_path)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(
                url_for("admin_dashboard") + "#projects-admin"
            )
        except Exception:
            app.logger.exception("Project image processing failed.")
            flash("Image process nahi ho saki. Please try again.", "error")
            return redirect(
                url_for("admin_dashboard") + "#projects-admin"
            )

    project = Project(
        title=title,
        location=location,
        description=description,
        image_url=image_url,
    )
    db.session.add(project)

    if safe_commit():
        flash("Project successfully add ho gaya.", "success")
    else:
        flash("Project save nahi ho saka.", "error")

    return redirect(url_for("admin_dashboard") + "#projects-admin")


@app.route("/admin/projects/<int:item_id>/delete", methods=["POST"])
@admin_required
def delete_project(item_id):
    item = db.get_or_404(Project, item_id)
    local_path = None

    if item.image_url and "uploads/projects/" in item.image_url:
        filename = item.image_url.rsplit("uploads/projects/", 1)[-1]

        # Only delete a filename, never a user-supplied arbitrary path.
        if filename and os.path.basename(filename) == filename:
            local_path = os.path.join(
                app.config["UPLOAD_FOLDER"], filename
            )

    db.session.delete(item)

    if safe_commit():
        if local_path and os.path.isfile(local_path):
            try:
                os.remove(local_path)
            except OSError:
                app.logger.warning(
                    "Could not delete local image: %s", local_path
                )
        flash("Project deleted.", "success")
    else:
        flash("Project delete nahi ho saka.", "error")

    return redirect(url_for("admin_dashboard") + "#projects-admin")


# --------------------------------------------------
# ADMIN INQUIRY MANAGEMENT
# --------------------------------------------------

@app.route("/admin/inquiries/<int:item_id>/update", methods=["POST"])
@admin_required
def update_inquiry(item_id):
    item = db.get_or_404(Inquiry, item_id)
    status = request.form.get("status", "")
    notes = request.form.get("admin_notes", "").strip()

    if status in {
        "New", "Contacted", "Accepted", "Rejected", "Completed"
    }:
        item.status = status

    item.admin_notes = notes

    if safe_commit():
        flash(
            f"Inquiry #{item.id} status & follow-up note update ho gaya.",
            "success",
        )
    else:
        flash("Inquiry update nahi ho saki.", "error")

    return redirect(url_for("admin_dashboard") + "#inquiries-admin")


@app.route("/admin/inquiries/<int:item_id>/delete", methods=["POST"])
@admin_required
def delete_inquiry(item_id):
    item = db.get_or_404(Inquiry, item_id)
    db.session.delete(item)

    if safe_commit():
        flash("Inquiry delete kar di gayi.", "success")
    else:
        flash("Inquiry delete nahi ho saki.", "error")

    return redirect(url_for("admin_dashboard") + "#inquiries-admin")


# --------------------------------------------------
# ADMIN SERVICE MANAGEMENT
# --------------------------------------------------

@app.route("/admin/services/add", methods=["POST"])
@admin_required
def add_service():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    price = (
        request.form.get("price_label", "").strip()
        or "Contact for quotation"
    )

    if not name or not description:
        flash("Service name aur description required hain.", "error")
    else:
        db.session.add(
            Service(
                name=name,
                description=description,
                price_label=price,
            )
        )

        if safe_commit():
            flash("Service catalog me add ho gayi.", "success")
        else:
            flash("Service save nahi ho saki.", "error")

    return redirect(url_for("admin_dashboard") + "#services-admin")


@app.route("/admin/services/<int:item_id>/delete", methods=["POST"])
@admin_required
def delete_service(item_id):
    item = db.get_or_404(Service, item_id)
    db.session.delete(item)

    if safe_commit():
        flash("Service remove ho gayi.", "success")
    else:
        flash("Service remove nahi ho saki.", "error")

    return redirect(url_for("admin_dashboard") + "#services-admin")


# --------------------------------------------------
# ADMIN REVIEW MANAGEMENT
# --------------------------------------------------

@app.route("/admin/reviews/add", methods=["POST"])
@admin_required
def add_existing_review():
    name = request.form.get("name", "").strip()
    location = request.form.get("location", "").strip()
    message = request.form.get("message", "").strip()

    try:
        rating = int(request.form.get("rating", "5"))
    except (TypeError, ValueError):
        rating = 0

    if not name or not message or rating not in range(1, 6):
        flash("Name, rating (1-5), aur message required hain.", "error")
    else:
        db.session.add(
            Review(
                name=name,
                location=location,
                message=message,
                rating=rating,
                approved=True,
            )
        )

        if safe_commit():
            flash("Customer review live publish ho gaya.", "success")
        else:
            flash("Review save nahi ho saka.", "error")

    return redirect(url_for("admin_dashboard") + "#reviews-admin")


@app.route("/admin/reviews/<int:review_id>/moderate", methods=["POST"])
@admin_required
def moderate_review(review_id):
    review = db.get_or_404(Review, review_id)
    action = request.form.get("action", "")

    if action == "approve":
        review.approved = True
        message = "Review publish ho gaya."
    elif action == "hide":
        review.approved = False
        message = "Review hide kar diya gaya."
    elif action == "delete":
        db.session.delete(review)
        message = "Review delete ho gaya."
    else:
        flash("Invalid review action.", "error")
        return redirect(
            url_for("admin_dashboard") + "#reviews-admin"
        )

    if safe_commit():
        flash(message, "success")
    else:
        flash("Review update nahi ho saka.", "error")

    return redirect(url_for("admin_dashboard") + "#reviews-admin")


# --------------------------------------------------
# ADMIN CSV EXPORT
# --------------------------------------------------

@app.route("/admin/export.csv")
@admin_required
def export_inquiries():
    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()

    query = Inquiry.query

    try:
        if start:
            start_date = date.fromisoformat(start)
            query = query.filter(
                Inquiry.created_at
                >= datetime.combine(start_date, time.min)
            )

        if end:
            end_date = date.fromisoformat(end)
            # Exclusive upper boundary includes the entire end date.
            query = query.filter(
                Inquiry.created_at
                < datetime.combine(end_date + timedelta(days=1), time.min)
            )
    except (ValueError, OverflowError):
        flash("Invalid date filter.", "error")
        return redirect(
            url_for("admin_dashboard") + "#inquiries-admin"
        )

    rows = query.order_by(Inquiry.created_at.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ID", "Date", "Time", "Name", "Phone", "Email", "City",
        "Service", "Message", "Status", "Admin Notes",
    ])

    for item in rows:
        created_at = item.created_at
        writer.writerow([
            item.id,
            created_at.strftime("%Y-%m-%d") if created_at else "",
            created_at.strftime("%H:%M:%S") if created_at else "",
            item.name,
            item.phone,
            item.email,
            item.city,
            item.service,
            item.message,
            item.status,
            item.admin_notes or "",
        ])

    filename = f"enquiries_{start or 'all'}_to_{end or 'all'}.csv"

    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


# --------------------------------------------------
# ADMIN WEBSITE SETTINGS
# --------------------------------------------------

@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        for key in DEFAULT_SETTINGS:
            value = request.form.get(key, "").strip()
            row = db.session.get(Setting, key)

            if row is None:
                db.session.add(Setting(key=key, value=value))
            else:
                row.value = value

        if safe_commit():
            flash("Website settings updated successfully.", "success")
            return redirect(url_for("admin_settings"))

        flash("Settings update nahi ho sakin.", "error")

    return render_template(
        "admin_settings.html", settings=get_settings()
    )


# --------------------------------------------------
# ADMIN PROFILE & PASSWORD
# --------------------------------------------------

@app.route("/admin/profile", methods=["GET", "POST"])
@admin_required
def admin_profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("current_password", "")

        if not name or not email:
            flash("Name aur email required hain.", "error")
        elif not current_user.check_password(password):
            flash("Current password galat hai.", "error")
        elif User.query.filter(
            User.email == email, User.id != current_user.id
        ).first():
            flash("Ye email kisi aur account se linked hai.", "error")
        else:
            current_user.name = name
            current_user.email = email

            if safe_commit():
                flash("Profile updated successfully.", "success")
                return redirect(url_for("admin_profile"))

            flash("Profile update nahi ho saka.", "error")

    return render_template("admin_profile.html")


@app.route("/admin/change-password", methods=["POST"])
@admin_required
def admin_change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not current_user.check_password(current_password):
        flash("Current password galat hai.", "error")
    elif len(new_password) < 10:
        flash(
            "New password must be at least 10 characters long.",
            "error",
        )
    elif new_password != confirm_password:
        flash("Passwords match nahi karte.", "error")
    elif new_password == current_password:
        flash("New password cannot be same as old password.", "error")
    else:
        current_user.set_password(new_password)

        if safe_commit():
            flash("Password successfully update ho gaya.", "success")
        else:
            flash("Password update nahi ho saka.", "error")

    return redirect(url_for("admin_profile") + "#password")


# --------------------------------------------------
# CLI: INITIALIZE DATABASE
# --------------------------------------------------

@app.cli.command("init-db")
def init_db():
    """Create database tables and add default services."""
    with app.app_context():
        db.create_all()

        defaults = [
            (
                "uPVC Windows & Sliders",
                "Soundproof, thermal-insulated, and dust-resistant "
                "window systems.",
                "Contact for quotation",
            ),
            (
                "Slim Line Swing Doors",
                "Ultra-thin profiles with maximum glass clarity "
                "and premium hardware.",
                "Contact for quotation",
            ),
            (
                "Acoustic Partitions",
                "Sound reduction and modern office / home glass "
                "partitions.",
                "Contact for quotation",
            ),
            (
                "Synchro | Telescopic",
                "Heavy-duty sliding and multi-track telescopic "
                "door systems.",
                "Contact for quotation",
            ),
        ]

        for name, description, price in defaults:
            existing = Service.query.filter_by(name=name).first()

            if existing is None:
                db.session.add(
                    Service(
                        name=name,
                        description=description,
                        price_label=price,
                    )
                )

        if not safe_commit():
            raise click.ClickException(
                "Database initialization failed. Check database settings."
            )

    click.echo("Database tables & default services initialized.")


# --------------------------------------------------
# CLI: CREATE ADMIN USER
# --------------------------------------------------

@app.cli.command("create-admin")
@click.option("--name", prompt="Admin Name")
@click.option("--email", prompt="Admin Email")
@click.password_option()
def create_admin(name, email, password):
    """Create an administrator account."""
    email = email.strip().lower()
    name = name.strip()

    if not name or not email:
        raise click.ClickException("Admin name and email are required.")

    if len(password) < 10:
        raise click.ClickException(
            "Admin password must contain at least 10 characters."
        )

    with app.app_context():
        db.create_all()

        if User.query.filter_by(email=email).first():
            click.echo("User already exists with this email.")
            return

        user = User(name=name, email=email, role="admin")
        user.set_password(password)
        db.session.add(user)

        if not safe_commit():
            raise click.ClickException(
                "Admin creation failed. Check database settings."
            )

    click.echo(f"Admin account created: {email}")


# --------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------

@app.errorhandler(403)
def forbidden(_error):
    return render_template(
        "error.html",
        code=403,
        message="Access forbidden. Admin permission required.",
    ), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template(
        "error.html",
        code=404,
        message="Page not found.",
    ), 404


@app.errorhandler(413)
def file_too_large(_error):
    flash("Uploaded file is too large. Maximum size is 25 MB.", "error")
    return redirect(request.referrer or url_for("index"))


@app.errorhandler(500)
def internal_server_error(_error):
    db.session.rollback()
    app.logger.exception("Internal server error.")
    return (
        render_template(
            "error.html",
            code=500,
            message="Something went wrong. Please try again later.",
        ),
        500,
    )


# --------------------------------------------------
# LOCAL DEVELOPMENT
# --------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=app.config["DEBUG"],
    )
