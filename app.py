"""
app.py - Main Flask app for school_report_portal
Feature-complete: routes for index, learner report (PDF), all learners report (PDF),
broadsheet (PDF), HTML views, and simple admin endpoints.

Adjust templates and DB schema mappings as needed.
"""
"""
app.py - Main Flask app for school_report_portal
Feature-complete: routes for index, learner report (PDF), all learners report (PDF),
broadsheet (PDF), HTML views, and simple admin endpoints.

Adjust templates and DB schema mappings as needed.
"""
import os
import logging
from io import BytesIO
from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, make_response, abort, flash
)
import pdfkit

from utils import (
    DB_PATH, get_all_learners, get_learner_by_id,
    get_broadsheet_data, get_all_learners_with_reports
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")  # change in prod
from export_word import export_word_bp
app.register_blueprint(export_word_bp)

# Add dashboard route for landing page (after app creation)
@app.route('/dashboard')
def dashboard():
    from utils import get_all_grades
    grades = get_all_grades()
    return render_template('landing.html', grades=grades)

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

# wkhtmltopdf path via env var (optional)
WKHTMLTOPDF_PATH = os.environ.get(
    "WKHTMLTOPDF_PATH",
    r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
)
if not os.path.exists(WKHTMLTOPDF_PATH):
    # try no configuration and rely on system path; warn if not found
    logger.warning("WKHTMLTOPDF_PATH not found at %s — relying on system PATH", WKHTMLTOPDF_PATH)
    PDFKIT_CONFIG = None
else:
    PDFKIT_CONFIG = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)

PDFKIT_OPTIONS = {
    "page-size": "A4",
    "encoding": "UTF-8",
    "enable-local-file-access": None,  # required for wkhtmltopdf to access local CSS
    "margin-top": "10mm",
    "margin-bottom": "10mm",
    "margin-left": "10mm",
    "margin-right": "10mm",
}

# ---------- Routes ----------


# Make dashboard the default landing page
@app.route("/")
def landing():
    return redirect(url_for('dashboard'))

@app.route("/learners")
def index():
    """Shows list of learners and simple actions, with grade filter."""
    from utils import get_all_grades, get_all_learners
    selected_grade = request.args.get('grade')
    grades = get_all_grades()
    if selected_grade:
        learners = [l for l in get_all_learners() if l['grade'] == selected_grade]
    else:
        learners = get_all_learners()
    return render_template("index.html", learners=learners, grades=grades, selected_grade=selected_grade)


@app.route("/learner/<int:learner_id>")
def view_learner(learner_id):
    """HTML view of a single learner report (not PDF)."""
    term = request.args.get('term')
    exam_type = request.args.get('exam_type')
    grade = request.args.get('grade')
    # Pass filters to get_learner_by_id
    learner = get_learner_by_id(learner_id, term=term, exam_type=exam_type, grade=grade)
    if not learner:
        abort(404, description="Learner not found")
    # For dropdowns
    terms = ['Term 1', 'Term 2', 'Term 3']
    exam_types = ['Opener', 'Midterm', 'Endterm']
    from utils import get_all_grades
    grades = get_all_grades()
    return render_template("learner_report.html", learner=learner, terms=terms, exam_types=exam_types, grades=grades, selected_term=term, selected_exam_type=exam_type, selected_grade=grade)


@app.route("/report/<int:learner_id>.pdf")
def report_pdf(learner_id):
    """
    Returns a PDF of a single learner report.
    Uses wkhtmltopdf via pdfkit; streams bytes to client (no temp files).
    """
    learner = get_learner_by_id(learner_id)
    if not learner:
        abort(404, description="Learner not found")

    # Render HTML using your Jinja template (ensure template exists)
    html = render_template("learner_report.html", learner=learner)
    try:
        pdf_bytes = pdfkit.from_string(html, False, options=PDFKIT_OPTIONS, configuration=PDFKIT_CONFIG)
    except Exception as e:
        logger.exception("Failed to generate PDF for learner_id=%s", learner_id)
        flash("PDF generation failed: " + str(e), "danger")
        return redirect(url_for("view_learner", learner_id=learner_id))

    return _bytes_to_pdf_response(pdf_bytes, filename=f"report_{learner['id']}.pdf")


@app.route("/reports/all.pdf")
def all_reports_pdf():
    """
    Generate a single PDF that lists all learners (e.g., summary reports).
    Template expected: all_learners_report.html
    """
    learners = get_all_learners_with_reports()
    html = render_template("all_learners_report.html", learners=learners)
    try:
        pdf_bytes = pdfkit.from_string(html, False, options=PDFKIT_OPTIONS, configuration=PDFKIT_CONFIG)
    except Exception as e:
        logger.exception("Failed to generate all reports PDF")
        flash("PDF generation failed: " + str(e), "danger")
        return redirect(url_for("index"))

    return _bytes_to_pdf_response(pdf_bytes, filename="all_learners_reports.pdf")


@app.route("/broadsheet/<grade>.pdf")
def broadsheet_pdf(grade):
    """
    Broadsheet grouped by grade/class.
    Template expected: broadsheet.html
    """
    try:
        data = get_broadsheet_data(grade)
    except Exception as e:
        logger.exception("Broadsheet fetch error for grade=%s", grade)
        abort(500, description="Error generating broadsheet")

    html = render_template("broadsheet.html", grade=grade, broadsheet=data)
    try:
        pdf_bytes = pdfkit.from_string(html, False, options=PDFKIT_OPTIONS, configuration=PDFKIT_CONFIG)
    except Exception as e:
        logger.exception("Failed to generate broadsheet PDF")
        abort(500, description="PDF generation failed")

    return _bytes_to_pdf_response(pdf_bytes, filename=f"broadsheet_{grade}.pdf")


@app.route("/grade_reports/<grade>/pdf")
def grade_reports_pdf(grade):
    """
    Generate a PDF containing individual reports for each learner in the selected grade.
    Each learner's report is on a separate page.
    """
    selected_term = request.args.get('term')
    selected_exam_type = request.args.get('exam_type')
    from utils import get_all_learners_with_reports, get_learner_by_id
    learners = [l for l in get_all_learners_with_reports() if l['grade'] == grade]
    # Render each learner's report as a separate page
    reports_html = ""
    terms = ['Term 1', 'Term 2', 'Term 3']
    exam_types = ['Opener', 'Midterm', 'Endterm']
    grades = [grade]
    for learner in learners:
        learner_full = get_learner_by_id(learner['id'], term=selected_term, exam_type=selected_exam_type, grade=grade)
        reports_html += render_template("learner_report.html", learner=learner_full, terms=terms, exam_types=exam_types, grades=grades, selected_term=selected_term, selected_exam_type=selected_exam_type, selected_grade=grade)
        reports_html += '<div style="page-break-after: always;"></div>'
    try:
        pdf_bytes = pdfkit.from_string(reports_html, False, options=PDFKIT_OPTIONS, configuration=PDFKIT_CONFIG)
    except Exception as e:
        logger.exception("Failed to generate grade reports PDF")
        flash("PDF generation failed: " + str(e), "danger")
        return redirect(url_for("grade_reports", grade=grade))
    return _bytes_to_pdf_response(pdf_bytes, filename=f"grade_{grade}_reports.pdf")


## Remove duplicate landing route. '/' now redirects to dashboard above.


# ---------- Utility endpoints ----------

@app.route("/health")
def health():
    return {"status": "ok", "db": DB_PATH}


# ---------- Helpers ----------

def _bytes_to_pdf_response(pdf_bytes: bytes, filename: str = "report.pdf"):
    """Helper to convert raw PDF bytes to a Flask response for download/view."""
    bio = BytesIO(pdf_bytes)
    bio.seek(0)
    return send_file(
        bio,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=filename
    )


# ---------- Error handlers ----------

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html", error=e), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("500.html", error=e), 500


# ---------- Run ----------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))  # Default to 5001
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
