"""Generate The Dojo — Feature Reference PDF for Product Details folder."""

import os
from fpdf import FPDF

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Product Details",
    "The_Dojo_Features.pdf",
)

# ─── Design constants ──────────────────────────────────────────────────────────
BG_DARK = (5, 5, 5)
BG_CARD = (18, 18, 18)
BG_ELEVATED = (28, 28, 28)
GOLD = (201, 169, 98)
GOLD_BRIGHT = (232, 213, 163)
GOLD_DIM = (139, 115, 85)
CYAN = (78, 205, 196)
PURPLE = (157, 78, 221)
GREEN = (0, 200, 100)
RED = (239, 68, 68)
TEXT_PRIMARY = (255, 255, 255)
TEXT_SECONDARY = (170, 170, 170)
TEXT_MUTED = (120, 120, 120)
BORDER = (40, 40, 40)


def _latin1_safe(text: str) -> str:
    """Replace Unicode chars that latin-1 core fonts can't render."""
    return (
        text
        .replace("\u2014", "--")   # em dash
        .replace("\u2013", "-")    # en dash
        .replace("\u2018", "'")    # left single quote
        .replace("\u2019", "'")    # right single quote
        .replace("\u201c", '"')    # left double quote
        .replace("\u201d", '"')    # right double quote
        .replace("\u2022", ">")    # bullet
        .replace("\u25B8", "-")    # right triangle
        .replace("\u2026", "...")  # ellipsis
    )


class DojoPDF(FPDF):
    def __init__(self):
        super().__init__("P", "mm", "Letter")
        self.set_auto_page_break(auto=True, margin=20)

    def normalize_text(self, text):
        return super().normalize_text(_latin1_safe(text))

    def _bg(self):
        self.set_fill_color(*BG_DARK)
        self.rect(0, 0, self.w, self.h, "F")

    def header(self):
        self._bg()
        if self.page_no() > 1:
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*GOLD_DIM)
            self.cell(0, 6, "Sovereign Sanctuary  |  The Dojo  |  Feature Reference", align="C")
            self.ln(3)
            self.set_draw_color(*GOLD_DIM)
            self.line(20, self.get_y(), self.w - 20, self.get_y())
            self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*TEXT_MUTED)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def section_title(self, title, color=GOLD):
        self.ln(4)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*color)
        self.cell(0, 10, title)
        self.ln(8)
        self.set_draw_color(*color)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(6)

    def sub_heading(self, text, color=GOLD_BRIGHT):
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*color)
        self.cell(0, 8, text)
        self.ln(7)

    def body_text(self, text, bold=False):
        self.set_font("Helvetica", "B" if bold else "", 9)
        self.set_text_color(*TEXT_SECONDARY)
        self.multi_cell(0, 5, text)
        self.ln(2)

    def bullet(self, label, desc, label_color=CYAN):
        x0 = self.get_x()
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*label_color)
        self.cell(4, 5, "> ")
        self.cell(0, 5, label)
        self.ln(5)
        if desc:
            self.set_x(x0 + 8)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*TEXT_SECONDARY)
            self.multi_cell(self.w - self.r_margin - x0 - 8, 4.5, desc)
            self.ln(1)

    def mode_card(self, name, price, persona_count, desc, personas):
        y_start = self.get_y()
        # Card background
        card_h = 12 + 5 * len(personas) + 8
        if y_start + card_h > self.h - 25:
            self.add_page()
            y_start = self.get_y()

        self.set_fill_color(*BG_CARD)
        self.set_draw_color(*BORDER)
        self.rect(self.l_margin, y_start, self.w - self.l_margin - self.r_margin, card_h, "DF")

        self.set_xy(self.l_margin + 4, y_start + 3)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*GOLD_BRIGHT)
        self.cell(90, 6, name)

        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*GREEN)
        self.cell(0, 6, price, align="R")
        self.ln(6)

        self.set_x(self.l_margin + 4)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*TEXT_SECONDARY)
        self.multi_cell(self.w - self.l_margin - self.r_margin - 8, 4, desc)
        self.ln(2)

        for p_name, p_desc in personas:
            self.set_x(self.l_margin + 8)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*CYAN)
            self.cell(3, 4.5, "- ")
            self.cell(50, 4.5, p_name)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*TEXT_MUTED)
            self.cell(0, 4.5, p_desc)
            self.ln(5)

        self.ln(6)

    def pricing_row(self, dojos, discount):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*TEXT_PRIMARY)
        self.set_fill_color(*BG_ELEVATED)
        self.cell(50, 7, f"{dojos} Dojo{'s' if dojos != 1 else ''}", border=0, fill=True)
        self.set_text_color(*GREEN if discount > 0 else TEXT_SECONDARY)
        self.cell(40, 7, f"{discount}% discount" if discount > 0 else "Standard price", border=0, fill=True, align="R")
        self.ln(7)


def build_pdf():
    pdf = DojoPDF()

    # ═══════════════════════════════════════════════════════════════════════════
    # COVER PAGE
    # ═══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.ln(50)
    pdf.set_font("Helvetica", "B", 36)
    pdf.set_text_color(*GOLD)
    pdf.cell(0, 14, "THE DOJO", align="C")
    pdf.ln(16)
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(*TEXT_SECONDARY)
    pdf.cell(0, 8, "AI-Powered Professional Training Platform", align="C")
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*TEXT_MUTED)
    pdf.cell(0, 7, "Part of the Sovereign Sanctuary Ecosystem", align="C")
    pdf.ln(6)
    pdf.cell(0, 7, "by Little Nate AI", align="C")
    pdf.ln(30)
    pdf.set_draw_color(*GOLD_DIM)
    pdf.line(60, pdf.get_y(), pdf.w - 60, pdf.get_y())
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*GOLD_DIM)
    pdf.cell(0, 7, "Complete Feature Reference", align="C")
    pdf.ln(6)
    pdf.cell(0, 7, "7 Professional Modes  |  42 AI Personas  |  Unlimited Sessions", align="C")

    # ═══════════════════════════════════════════════════════════════════════════
    # TABLE OF CONTENTS
    # ═══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("Table of Contents")
    toc = [
        "1.  What Is The Dojo?",
        "2.  Dojo Modes Overview",
        "3.  Therapist Dojo",
        "4.  Project PM Dojo",
        "5.  Business Dojo",
        "6.  CNC Machinist Dojo",
        "7.  MCAT Prep Dojo",
        "8.  Teacher Dojo",
        "9.  Judge Nate Dojo",
        "10. Subscription & Pricing",
        "11. Assessments & Exports",
        "12. Night School Integration",
        "13. Security & Adversarial Testing",
    ]
    for item in toc:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*TEXT_PRIMARY)
        pdf.cell(0, 7, item)
        pdf.ln(7)

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. WHAT IS THE DOJO?
    # ═══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("1. What Is The Dojo?")
    pdf.body_text(
        "The Dojo is Sovereign Sanctuary's adversarial and professional training environment. "
        "It provides AI-powered simulation sessions where coaches and professionals practice "
        "their skills against realistic AI personas. Each session is analyzed in real time by "
        "Little Nate, who scores responses, detects safety violations, and extracts learnings "
        "that feed back into the platform's Night School wisdom system."
    )
    pdf.ln(2)
    pdf.sub_heading("Core Capabilities")
    pdf.bullet("Real-Time AI Analysis",
               "Every response is evaluated for accuracy, safety, and best-practice adherence.")
    pdf.bullet("42 Specialized Personas",
               "From hostile therapy clients to courtroom simulations, each persona tests a specific professional skill.")
    pdf.bullet("Unlimited Sessions",
               "Dojo sessions consume zero AI tokens. Practice as much as needed.")
    pdf.bullet("Assessment Generation",
               "Generate timed practice exams with answer keys and scoring in PDF format.")
    pdf.bullet("Professional Exports",
               "PM and Business modes export Gantt charts (PDF) and structured workbooks (Excel).")
    pdf.bullet("Wisdom Extraction",
               "Strong responses and insights are auto-extracted into Night School for continuous improvement.")

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. DOJO MODES OVERVIEW
    # ═══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("2. Dojo Modes Overview")
    pdf.body_text(
        "The Dojo offers 7 professional training modes. Each mode contains a set of AI personas "
        "that simulate domain-specific scenarios. Coaches subscribe to one or more modes and "
        "receive volume discounts for multi-mode subscriptions."
    )
    pdf.ln(2)

    modes_summary = [
        ("Therapist Dojo", "$175/mo", "9 personas", "Crisis intervention, hostile clients, boundary testing, adversarial security."),
        ("Project PM Dojo", "$250/mo", "6 personas", "Sprint planning, stakeholder conflicts, lean process optimization."),
        ("Business Dojo", "$325/mo", "6 personas", "Pitch practice, financial analysis, market strategy, leadership."),
        ("CNC Machinist Dojo", "$150/mo", "6 personas", "Toolpath optimization, G-code debugging, GD&T interpretation."),
        ("MCAT Prep Dojo", "$500/mo", "6 personas", "Full MCAT section coverage, practice assessments, score analysis."),
        ("Teacher Dojo", "$225/mo", "8 personas", "Pedagogy, classroom management, SEL, cultural competency."),
        ("Judge Nate Dojo", "$2,100/mo", "6 personas", "Bar exam prep, courtroom simulation, case analysis, LexisNexis."),
    ]
    for name, price, count, desc in modes_summary:
        pdf.set_fill_color(*BG_CARD)
        pdf.set_draw_color(*BORDER)
        y0 = pdf.get_y()
        h = 18
        if y0 + h > pdf.h - 25:
            pdf.add_page()
            y0 = pdf.get_y()
        pdf.rect(pdf.l_margin, y0, pdf.w - pdf.l_margin - pdf.r_margin, h, "DF")
        pdf.set_xy(pdf.l_margin + 4, y0 + 2)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*GOLD_BRIGHT)
        pdf.cell(80, 5, name)
        pdf.set_text_color(*GREEN)
        pdf.cell(25, 5, price)
        pdf.set_text_color(*CYAN)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, count, align="R")
        pdf.set_xy(pdf.l_margin + 4, y0 + 9)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*TEXT_SECONDARY)
        pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin - 8, 4, desc)
        pdf.set_y(y0 + h + 3)

    # ═══════════════════════════════════════════════════════════════════════════
    # 3-9. INDIVIDUAL MODE PAGES
    # ═══════════════════════════════════════════════════════════════════════════

    # --- 3. THERAPIST ---
    pdf.add_page()
    pdf.section_title("3. Therapist Dojo", CYAN)
    pdf.body_text(
        "The Therapist Dojo trains mental health professionals in crisis intervention, "
        "boundary management, and safety protocol adherence. It also includes adversarial "
        "security personas that test the AI platform's resilience against prompt injection, "
        "resource exhaustion, and data poisoning attacks."
    )
    pdf.ln(2)
    pdf.sub_heading("Personas", CYAN)
    personas_therapist = [
        ("Hostile Client", "Simulates an aggressive, confrontational client testing de-escalation skills."),
        ("Crisis / Suicidal Ideation", "Tests crisis intervention protocols, safety resource delivery, and mandatory reporting."),
        ("Skeptic", "Questions therapy validity, challenges credentials, tests response to pushback."),
        ("Minor (Age 12)", "A child user requiring age-appropriate responses, parental consent protocols."),
        ("Manipulative", "Social engineering attempts, boundary violations, information extraction."),
        ("Boundary Tester", "Pushes professional boundaries — personal questions, dual relationships."),
        ("Prompt Injection", "Red-team security testing of AI system defenses."),
        ("Resource Exhaustion", "Token flooding and rate limit stress testing."),
        ("Data Poisoning", "False data injection to test input validation."),
    ]
    for name, desc in personas_therapist:
        pdf.bullet(name, desc)

    pdf.ln(2)
    pdf.sub_heading("Analysis Metrics", CYAN)
    pdf.bullet("Safety Violations", "Detects missing crisis resources, boundary breaches, confidentiality failures.")
    pdf.bullet("Clinical Accuracy", "Scores therapeutic technique quality and evidence-based practice adherence.")
    pdf.bullet("De-escalation Skill", "Rates effectiveness of calming and redirecting hostile interactions.")
    pdf.bullet("Wisdom Compliance", "Checks responses against Night School approved therapeutic guidelines.")

    # --- 4. PROJECT PM ---
    pdf.add_page()
    pdf.section_title("4. Project PM Dojo", PURPLE)
    pdf.body_text(
        "The Project PM Dojo trains project managers in agile methodology, stakeholder "
        "management, risk assessment, and lean process optimization. Sessions can export "
        "Gantt charts and structured workbooks for real project planning."
    )
    pdf.ln(2)
    pdf.sub_heading("Personas", PURPLE)
    personas_pm = [
        ("Sprint Planning", "Facilitates sprint ceremonies — backlog selection, capacity planning, story pointing."),
        ("Backlog Grooming", "Prioritization exercises, user story refinement, acceptance criteria writing."),
        ("Stakeholder Conflict", "Mediates competing stakeholder interests, scope management, expectation setting."),
        ("Risk Assessment", "Risk identification, probability/impact analysis, mitigation planning."),
        ("Retrospective", "Team retrospective facilitation, action item generation, improvement tracking."),
        ("Lean / Waste", "Lean process analysis, waste identification (8 wastes), value stream mapping."),
    ]
    for name, desc in personas_pm:
        pdf.bullet(name, desc, PURPLE)

    pdf.ln(2)
    pdf.sub_heading("Export Features", PURPLE)
    pdf.bullet("Gantt Chart PDF", "Extracts project timeline from conversation and generates a visual Gantt chart.")
    pdf.bullet("Excel Workbook", "Structured workbook with tasks, assignments, timelines, and dependencies.")

    # --- 5. BUSINESS ---
    pdf.add_page()
    pdf.section_title("5. Business Dojo", GREEN)
    pdf.body_text(
        "The Business Dojo develops entrepreneurial and executive skills. From pitch "
        "refinement to financial modeling, it covers the full spectrum of business leadership."
    )
    pdf.ln(2)
    pdf.sub_heading("Personas", GREEN)
    personas_biz = [
        ("Pitch Practice", "Business pitch coaching with investor-style questioning and feedback."),
        ("Financial Analysis", "Financial statement interpretation, ratio analysis, forecasting."),
        ("Market Strategy", "Market entry strategy, competitive analysis, positioning."),
        ("Client Acquisition", "Sales process design, pipeline management, conversion optimization."),
        ("Operations", "Operational efficiency, supply chain, process improvement."),
        ("Leadership", "Leadership development, team dynamics, organizational culture."),
    ]
    for name, desc in personas_biz:
        pdf.bullet(name, desc, GREEN)

    pdf.ln(2)
    pdf.sub_heading("Export Features", GREEN)
    pdf.bullet("Gantt Chart PDF", "Business plan timeline visualization with milestones.")
    pdf.bullet("Excel Workbook", "Financial models, market analysis frameworks, and action plans.")

    # --- 6. CNC ---
    pdf.add_page()
    pdf.section_title("6. CNC Machinist Dojo", (255, 149, 0))
    pdf.body_text(
        "The CNC Machinist Dojo trains machinists and manufacturing engineers in toolpath "
        "optimization, G-code debugging, material selection, and geometric dimensioning "
        "and tolerancing (GD&T)."
    )
    pdf.ln(2)
    pdf.sub_heading("Personas", (255, 149, 0))
    personas_cnc = [
        ("Toolpath Optimization", "Feed rate, stepover, and cutting strategy optimization for various materials."),
        ("G-Code Review", "G-code debugging, syntax validation, and program optimization."),
        ("Material Selection", "Material properties, machinability ratings, cutting parameter selection."),
        ("Fixture Setup", "Workholding challenges, clamping strategies, datum reference selection."),
        ("Tolerance Analysis", "GD&T interpretation, tolerance stack-up analysis, inspection planning."),
        ("Machine Troubleshoot", "Diagnostic skills for CNC machine issues — vibration, chatter, tool wear."),
    ]
    for name, desc in personas_cnc:
        pdf.bullet(name, desc, (255, 149, 0))

    # --- 7. MCAT ---
    pdf.add_page()
    pdf.section_title("7. MCAT Prep Dojo", (0, 212, 255))
    pdf.body_text(
        "The MCAT Prep Dojo provides comprehensive medical school entrance exam preparation "
        "across all four MCAT sections. Features timed practice assessments with scoring "
        "and score trajectory analysis."
    )
    pdf.ln(2)
    pdf.sub_heading("Personas", (0, 212, 255))
    personas_mcat = [
        ("Biology / Biochemistry", "Section 1 content — molecular biology, genetics, metabolism, organ systems."),
        ("Chemistry / Physics", "Section 2 content — general chemistry, organic chemistry, physics."),
        ("Psychology / Sociology", "Section 3 content — behavioral sciences, social determinants of health."),
        ("CARS Passage", "Critical Analysis and Reasoning Skills — reading comprehension, argument analysis."),
        ("Full Assessment", "Timed full-length practice exams across all sections."),
        ("Score Analysis", "Score trajectory tracking, weakness identification, study plan optimization."),
    ]
    for name, desc in personas_mcat:
        pdf.bullet(name, desc, (0, 212, 255))

    pdf.ln(2)
    pdf.sub_heading("Assessment Features", (0, 212, 255))
    pdf.bullet("PDF Exam Generation", "Generates timed practice exams with configurable question count and focus areas.")
    pdf.bullet("Auto-Scoring", "Upload completed exams for AI-powered scoring and detailed feedback.")
    pdf.bullet("Score History", "Track progress over time with historical score visualization.")

    # --- 8. TEACHER ---
    pdf.add_page()
    pdf.section_title("8. Teacher Dojo", (255, 107, 157))
    pdf.body_text(
        "The Teacher Dojo develops K-12 educators across pedagogy, classroom management, "
        "social-emotional learning, and culturally responsive teaching practices."
    )
    pdf.ln(2)
    pdf.sub_heading("Personas", (255, 107, 157))
    personas_teacher = [
        ("Content Mastery", "Multi-disciplinary knowledge assessment across grade levels and subjects."),
        ("Pedagogy", "Curriculum design, differentiated instruction, learning objectives."),
        ("Classroom Management", "Behavior management strategies, de-escalation, positive reinforcement."),
        ("Social-Emotional Learning", "SEL integration, emotional regulation support, trauma-informed practices."),
        ("Interdisciplinary", "Cross-curricular connections, project-based learning design."),
        ("Tech & AI Integration", "Educational technology, AI tools for instruction, digital literacy."),
        ("Communication", "Parent/guardian conferences, colleague collaboration, IEP meetings."),
        ("Cultural Competency", "Inclusive teaching, cultural responsiveness, equity-centered practices."),
    ]
    for name, desc in personas_teacher:
        pdf.bullet(name, desc, (255, 107, 157))

    # --- 9. JUDGE NATE ---
    pdf.add_page()
    pdf.section_title("9. Judge Nate Dojo", RED)
    pdf.body_text(
        "The Judge Nate Dojo is the premium tier of The Dojo, providing comprehensive "
        "legal training for bar exam preparation, courtroom simulation, and case analysis. "
        "It includes LexisNexis integration for real case law research and a student "
        "mentoring system with admin-verified access."
    )
    pdf.ln(2)
    pdf.sub_heading("Personas", RED)
    personas_judge = [
        ("Bar Exam Prep", "Uniform Bar Exam preparation with MBE, MEE, and MPT question formats."),
        ("Case Analysis", "Case law analysis, precedent identification, distinguishing holdings from dicta."),
        ("Courtroom Simulation", "Full courtroom scenarios — direct/cross examination, objections, motions."),
        ("Judicial Reasoning", "Legal reasoning frameworks, constitutional interpretation, statutory analysis."),
        ("Oral Argument", "Appellate oral argument practice with bench questioning simulation."),
        ("Ethics & Compliance", "Legal ethics (MPRE), professional responsibility, conflicts of interest."),
    ]
    for name, desc in personas_judge:
        pdf.bullet(name, desc, RED)

    pdf.ln(2)
    pdf.sub_heading("Exclusive Features", RED)
    pdf.bullet("LexisNexis Integration",
               "Search real case law, statutes, and regulations during sessions via OAuth 2.0 API.")
    pdf.bullet("Case Document Upload",
               "Upload PDF case documents for AI reference during training sessions. "
               "Supports civil, criminal, appellate, and constitutional case types.")
    pdf.bullet("Student Verification",
               "Coaches submit student verification requests reviewed by admin. Approved students "
               "receive a Judge Nate Bar ID (JNBAR-XXXXXX) for tracked access.")
    pdf.bullet("Debate Portal",
               "Coach-vs-coach debate sessions with AI moderation and scoring.")
    pdf.bullet("Bar ID System",
               "Each verified participant receives a unique Bar ID for progress tracking across sessions.")

    # ═══════════════════════════════════════════════════════════════════════════
    # 10. SUBSCRIPTION & PRICING
    # ═══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("10. Subscription & Pricing")
    pdf.body_text(
        "Each Dojo mode operates on a 12-month subscription term with auto-renewal. "
        "Coaches can subscribe to multiple modes and receive volume discounts. Cancelled "
        "subscriptions retain access until the end of the current billing term."
    )
    pdf.ln(2)
    pdf.sub_heading("Monthly Pricing")

    prices = [
        ("Therapist Dojo", "$175"),
        ("CNC Machinist Dojo", "$150"),
        ("Teacher Dojo", "$225"),
        ("Project PM Dojo", "$250"),
        ("Business Dojo", "$325"),
        ("MCAT Prep Dojo", "$500"),
        ("Judge Nate Dojo", "$2,100"),
    ]
    for name, price in prices:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_fill_color(*BG_CARD)
        pdf.set_text_color(*TEXT_PRIMARY)
        pdf.cell(100, 7, f"  {name}", fill=True)
        pdf.set_text_color(*GREEN)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 7, price, fill=True, align="R")
        pdf.ln(8)

    pdf.ln(4)
    pdf.sub_heading("Multi-Dojo Volume Discounts")
    pdf.body_text(
        "Subscribe to multiple Dojo modes and receive automatic discounts on all non-Judge subscriptions. "
        "The Judge Nate Dojo is always billed at full price ($2,100/mo) regardless of bundle size."
    )
    pdf.ln(2)

    discounts = [
        (1, 0), (2, 10), (3, 15), (4, 20), (5, 25), (6, 30),
    ]
    for count, disc in discounts:
        pdf.pricing_row(count, disc)

    pdf.ln(4)
    pdf.sub_heading("Subscription Terms")
    pdf.bullet("Term Length", "12 months with auto-renewal at the then-current rate.")
    pdf.bullet("Cancellation", "Cancel anytime. Access continues until the term end date.")
    pdf.bullet("Discount Recalculation", "Adding or removing modes automatically recalculates discounts for all active subscriptions.")

    # ═══════════════════════════════════════════════════════════════════════════
    # 11. ASSESSMENTS & EXPORTS
    # ═══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("11. Assessments & Exports")
    pdf.body_text(
        "The Dojo includes a comprehensive assessment system for generating practice exams "
        "and professional exports."
    )
    pdf.ln(2)
    pdf.sub_heading("Assessment System")
    pdf.bullet("Preview Assessment", "Preview question sets before generating a full PDF exam.")
    pdf.bullet("Generate PDF Exam", "Create mode-specific assessments with configurable difficulty, focus areas, and question count.")
    pdf.bullet("Answer Key Generation", "Each assessment includes a separate answer key PDF for self-grading.")
    pdf.bullet("AI-Powered Scoring", "Upload completed assessments for AI text extraction and automated scoring.")
    pdf.bullet("Assessment History", "Track all completed assessments with scores and timestamps per mode.")

    pdf.ln(2)
    pdf.sub_heading("Professional Exports (PM & Business)")
    pdf.bullet("Gantt Chart (PDF)",
               "Analyzes conversation content and extracts a project timeline into a visual Gantt chart.")
    pdf.bullet("Excel Workbook",
               "Generates a structured workbook with tasks, owners, deadlines, dependencies, and status columns.")

    pdf.ln(2)
    pdf.sub_heading("Case Documents (Judge Only)")
    pdf.bullet("PDF Case Upload",
               "Upload legal case documents in PDF format. AI extracts text for reference during sessions.")
    pdf.bullet("Case Management",
               "Browse, search, and manage uploaded cases organized by type: civil, criminal, appellate, constitutional.")
    pdf.bullet("LexisNexis Search",
               "Search live case law and statutes via integrated LexisNexis API during Judge Dojo sessions.")

    # ═══════════════════════════════════════════════════════════════════════════
    # 12. NIGHT SCHOOL INTEGRATION
    # ═══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("12. Night School Integration")
    pdf.body_text(
        "The Dojo and Night School operate as a feedback loop. Night School provides "
        "the approved wisdom and guidelines that the Dojo uses to analyze responses. "
        "Strong Dojo performances generate new wisdom entries that flow back into Night School."
    )
    pdf.ln(2)
    pdf.sub_heading("Night School -> Dojo")
    pdf.bullet("Wisdom-Informed Analysis",
               "Dojo analysis references approved Night School wisdom entries when scoring responses.")
    pdf.bullet("Violation Detection",
               "Identifies when responses contradict approved therapeutic guidelines or best practices.")

    pdf.ln(2)
    pdf.sub_heading("Dojo -> Night School")
    pdf.bullet("Auto-Learning Extraction",
               "After each session, strong responses and novel insights are extracted as candidate wisdom entries.")
    pdf.bullet("Tagged Entries",
               "Extracted learnings are tagged with the Dojo mode, persona, and 'auto_learned' or 'positive_example'.")
    pdf.bullet("Coach Approval Flow",
               "Extracted entries go through the standard Night School approval pipeline before becoming active wisdom.")

    # ═══════════════════════════════════════════════════════════════════════════
    # 13. SECURITY & ADVERSARIAL TESTING
    # ═══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("13. Security & Adversarial Testing")
    pdf.body_text(
        "The Therapist Dojo includes three adversarial security personas designed to test "
        "the AI platform's resilience against common attack vectors. These are red-team "
        "tools for platform security validation."
    )
    pdf.ln(2)
    pdf.sub_heading("Adversarial Personas")
    pdf.bullet("Prompt Injection",
               "Tests system prompt boundary enforcement. Simulates attempts to override AI instructions, "
               "extract system prompts, or make the AI behave outside its guidelines.")
    pdf.bullet("Resource Exhaustion",
               "Stress-tests token limits and rate limiters. Simulates flooding attacks designed to "
               "exhaust API quotas or crash the system through excessive requests.")
    pdf.bullet("Data Poisoning",
               "Tests input validation and data integrity. Simulates injection of false or malicious data "
               "designed to corrupt the AI's knowledge base or decision-making.")

    pdf.ln(4)
    pdf.sub_heading("Session Security")
    pdf.bullet("Zero Token Cost",
               "All Dojo sessions are marked as simulations and consume zero AI tokens from the coach's balance.")
    pdf.bullet("Analytics Isolation",
               "Dojo activity is excluded from engagement analytics to keep real usage metrics clean.")
    pdf.bullet("Simulation Tagging",
               "Every Dojo message is prefixed with [DOJO SIMULATION - MODE / PERSONA] to prevent "
               "confusion with real client interactions.")
    pdf.bullet("Session Logging",
               "All sessions are logged to isolated files (dojo_{session_id}.json) for audit trail and review.")

    # ═══════════════════════════════════════════════════════════════════════════
    # BACK COVER
    # ═══════════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.ln(60)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(*GOLD)
    pdf.cell(0, 12, "Sovereign Sanctuary", align="C")
    pdf.ln(14)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*TEXT_SECONDARY)
    pdf.cell(0, 7, "The Dojo  |  Night School  |  Little Nate AI", align="C")
    pdf.ln(20)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*TEXT_MUTED)
    pdf.cell(0, 6, "app.sovereignsanctuary.net", align="C")
    pdf.ln(6)
    pdf.cell(0, 6, "coach.sovereignsanctuary.net", align="C")
    pdf.ln(6)
    pdf.cell(0, 6, "command.sovereignsanctuary.net", align="C")
    pdf.ln(20)
    pdf.set_draw_color(*GOLD_DIM)
    pdf.line(70, pdf.get_y(), pdf.w - 70, pdf.get_y())
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(*GOLD_DIM)
    pdf.cell(0, 6, "Confidential  |  For Internal & Partner Use", align="C")

    # ── Save ──
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    pdf.output(OUTPUT_PATH)
    print(f"PDF saved to: {OUTPUT_PATH}")
    print(f"Pages: {pdf.page_no()}")


if __name__ == "__main__":
    build_pdf()
