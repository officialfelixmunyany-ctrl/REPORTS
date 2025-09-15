"""
utils.py - database helpers for school_report_portal
Provides safe sqlite3 helpers. Adjust SQL to match your actual DB schema.
"""
import os
import sqlite3
from typing import List, Dict, Optional

DB_PATH = r"C:\\Users\\offic\\Desktop\\Projects\\misc_scripts\\school_exam_portal.db"


def get_conn(path: str = DB_PATH) -> sqlite3.Connection:
    """Return a sqlite3 connection with row_factory for dict-like rows."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def get_all_learners() -> List[Dict]:
    """
    Return list of learners. Adjust columns to fit your schema.
    Example expected columns: id, full_name, admission_no, grade
    """
    sql = "SELECT id, full_name, grade FROM learners ORDER BY full_name"
    with get_conn() as conn:
        cur = conn.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
    return rows


def get_all_learners_with_reports() -> List[Dict]:
    """
    Returns a list of learners with minimal report summary (used for all_learners report).
    Modify query to join marks/averages if your DB supports it.
    """
    sql = """
    SELECT l.id, l.full_name, l.grade,
        (SELECT AVG(score) FROM scores s WHERE s.learner_id = l.id) AS average_score
    FROM learners l
    ORDER BY l.full_name
    """
    with get_conn() as conn:
        cur = conn.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
    return rows


def get_learner_by_id(learner_id: int, term: str = None, exam_type: str = None, grade: str = None) -> Optional[Dict]:
    """
    Return detailed learner data including marks, comments, etc. Filters by term, exam_type, and grade if provided.
    """
    learner_sql = "SELECT id, full_name, grade FROM learners WHERE id = ?"
    # Get all subjects for this learner's grade (or selected grade)
    subjects_sql = """
        SELECT s.id, s.name FROM subjects s
        JOIN grade_subjects gs ON gs.subject_id = s.id
        WHERE gs.grade = ?
        ORDER BY s.name
    """
    # Get all scores for this learner, filtered
    scores_sql_base = """
        SELECT s.id AS subject_id, s.name AS subject, sc.exam_type, sc.term, sc.score
        FROM scores sc
        JOIN subjects s ON s.id = sc.subject_id
        WHERE sc.learner_id = ?
    """
    scores_filters = []
    params = [learner_id]
    if term:
        scores_filters.append("sc.term = ?")
        params.append(term)
    if exam_type:
        scores_filters.append("sc.exam_type = ?")
        params.append(exam_type)
    scores_sql = scores_sql_base
    if scores_filters:
        scores_sql += " AND " + " AND ".join(scores_filters)
    scores_sql += " ORDER BY s.name"
    # Class average and highest for each subject
    class_avg_sql = """
        SELECT AVG(score) as avg_score, MAX(score) as max_score
        FROM scores
        WHERE subject_id = ?
    """
    class_avg_filters = []
    def add_filter(val, col):
        if val:
            class_avg_filters.append(f"{col} = ?")
            return True
        return False
    # Get grade for subjects
    with get_conn() as conn:
        cur = conn.execute(learner_sql, (learner_id,))
        row = cur.fetchone()
        if not row:
            return None
        learner = dict(row)
        grade_val = grade if grade else learner['grade']
        subjects = cur.execute(subjects_sql, (grade_val,)).fetchall()
        subject_map = {s['id']: s['name'] for s in subjects}
        # Get scores for this learner
        scores = cur.execute(scores_sql, tuple(params)).fetchall()
        marks = []
        total_score_obtained = 0
        total_score_obtainable = 0
        for s in scores:
            subj_id = s['subject_id']
            subj_name = s['subject']
            exam_type_val = s['exam_type']
            term_val = s['term']
            score = s['score']
            total_score_obtained += score if score is not None else 0
            total_score_obtainable += 100  # assuming max per subject is 100
            # Class average/highest filters
            avg_params = [subj_id]
            avg_sql = class_avg_sql
            avg_filters = []
            if term:
                avg_filters.append("term = ?")
                avg_params.append(term)
            if exam_type:
                avg_filters.append("exam_type = ?")
                avg_params.append(exam_type)
            if avg_filters:
                avg_sql += " AND " + " AND ".join(avg_filters)
            avg_row = cur.execute(avg_sql, tuple(avg_params)).fetchone()
            class_average = round(avg_row['avg_score'], 1) if avg_row and avg_row['avg_score'] is not None else None
            class_highest = round(avg_row['max_score'], 1) if avg_row and avg_row['max_score'] is not None else None
            # Remarks
            if score >= 80:
                remarks = 'exceeding expectations'
            elif score >= 65:
                remarks = 'meeting expectations'
            elif score >= 50:
                remarks = 'approaching expectations'
            else:
                remarks = 'below expectations'
            marks.append({
                'subject': subj_name,
                'exam_type': exam_type_val,
                'score': score,
                'class_average': class_average,
                'remarks': remarks,
                'class_highest': class_highest
            })
        learner['marks'] = marks
        learner['total_score_obtainable'] = total_score_obtainable
        learner['total_score_obtained'] = total_score_obtained
        learner['average_percentage'] = round((total_score_obtained / total_score_obtainable) * 100, 1) if total_score_obtainable else 0
        # Comments and dates (placeholder, can be fetched from DB if available)
        learner['teacher_comments'] = None
        learner['principal_comments'] = None
        learner['teacher_date'] = None
        learner['principal_date'] = None
    return learner


def get_broadsheet_data(grade: str) -> Dict:
    """
    Returns broadsheet info for a grade/class.
    Expected to return a dict with:
    - 'subjects': [subject names...]
    - 'learners': [{ id, full_name, marks: {subject:score, ...} }, ...]
    Adjust SQL logic to match your DB.
    """
    # Get subjects for the grade (all subjects)
    subjects_sql = """
    SELECT DISTINCT s.name
    FROM subjects s
    ORDER BY s.name
    """
    # Get learners in grade and their scores pivoted
    learners_sql = "SELECT id, full_name FROM learners WHERE grade = ? ORDER BY full_name"
    marks_sql = "SELECT sc.learner_id, s.name as subject, sc.score FROM scores sc JOIN subjects s ON s.id = sc.subject_id WHERE sc.learner_id IN ({placeholders})"

    with get_conn() as conn:
        subjects = [r["name"] for r in conn.execute(subjects_sql).fetchall()]

        learners = [dict(r) for r in conn.execute(learners_sql, (grade,)).fetchall()]
        if not learners:
            return {"subjects": subjects, "learners": []}

        learner_ids = [str(l["id"]) for l in learners]
        placeholders = ",".join("?" for _ in learner_ids)
        marks_query = marks_sql.replace("{placeholders}", placeholders)
        params = tuple(int(i) for i in learner_ids)
        rows = conn.execute(marks_query, params).fetchall()

        # pivot marks into learner -> {subject: score}
        marks_by_learner = {}
        for r in rows:
            lid = r["learner_id"]
            marks_by_learner.setdefault(lid, {})[r["subject"]] = r["score"]

        # attach marks dict to each learner
        for l in learners:
            l_id = l["id"]
            l["marks"] = marks_by_learner.get(l_id, {})

    return {"subjects": subjects, "learners": learners}


def get_all_grades() -> list:
    """Return a sorted list of all unique grades in the learners table."""
    sql = "SELECT DISTINCT grade FROM learners ORDER BY grade"
    with get_conn() as conn:
        cur = conn.execute(sql)
        return [r[0] for r in cur.fetchall()]
