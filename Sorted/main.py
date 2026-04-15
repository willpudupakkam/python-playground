from collections import Counter
import re
import sys
import csv
import json
import os
import asyncio
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QTableWidget, QTableWidgetItem, QScrollArea,
    QStyledItemDelegate, QStyleOptionViewItem, QAbstractScrollArea, QStyle,
    QComboBox, QSpinBox, QToolButton
)
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtCore import Qt

from requisites import *
from offered import *

c = 0
v = 0

class Course:
    '''
    self.subject = The course subject (PHYS, AMATH, etc.)
    self.catalog = The course catalog ID (i.e. catalog ID of PHYS 444 is 444)
    self.offered = The term(s) that the course is offered (str of the form 'FWS', only includes letters of terms in which the course is offered)
    self.prereqs = A list of prerequisite courses for the course (list of str, like ['AMATH 231', 'AMATH 250'])
    self.coreqs = A list of corequisite courses for the course (list of str, like ['AMATH 231', 'AMATH 250'])
    '''
    def __init__(self, subject, catalog, offered, prereqs, coreqs):
        self.subject = subject
        self.catalog = catalog
        self.offered = offered
        self.prereqs = prereqs
        self.coreqs = coreqs

    def __repr__(self):
        return f'{self.subject} {self.catalog}'
    
    def get_info(self):
        return {'course': f'{self.subject} {self.catalog}', \
                'offered': self.offered, \
                    'prerequisites': self.prereqs, \
                        'corequisites': self.coreqs}

termlist = ['W', 'S', 'F', 'W'] # input
counts = {}
ordered_termlist = []
for term in termlist:
    counts[term] = counts.get(term, 0) + 1
    ordered_termlist.append(term + str(counts[term]))

str_courselist = ['PHYS 359', 
                  'PHYS 434',
                  'PHYS 442', 
                  'PHYS 444', 
                  'AMATH 331', 
                  'AMATH 332', 
                  'AMATH 333', 
                  'AMATH 353', 
                  'PHYS 334', 
                  'AMATH 445', 
                  'AMATH 473', 
                  'AMATH 475', 
                  'CS 230', 
                  'CS 370', 
                  'CS 467', 
                  'CS 475', 
                  'CS 479'] # input

# Load existing courses from CSV (read mode)
existing = {}
try:
    with open("courses_learned.csv", mode="r", newline="") as rf:
        reader = csv.DictReader(rf)
        for row in reader:
            # index by course string, e.g. "PHYS 444"
            existing[row["course"]] = row
except FileNotFoundError:
    # no cache yet
    pass

# Define all Course objects & add them to a master list
raw_courselist = []
for course in str_courselist:
    if course in existing:
        row = existing[course]
        # The CSV stores full "course" like "PHYS 444" — split into subject/catalog
        try:
            subject, catalog = row["course"].split()
        except Exception:
            subject = course.split(" ")[0]
            catalog = course.split(" ")[1]
        offered = row.get("offered", "")
        # prerequisites/corequisites are stored as JSON strings in the CSV
        pr_raw = row.get("prerequisites", "[]")
        cr_raw = row.get("corequisites", "[]")
        try:
            pr_lst = json.loads(pr_raw) if isinstance(pr_raw, str) else pr_raw
        except Exception:
            pr_lst = []
        try:
            cr_lst = json.loads(cr_raw) if isinstance(cr_raw, str) else cr_raw
        except Exception:
            cr_lst = []
        raw_courselist.append(Course(subject, catalog, offered, pr_lst, cr_lst))
    else:
        subject = course.split(" ")[0]
        catalog = course.split(" ")[1]

        # fetch from helpers
        reqs = asyncio.run(get_reqs(course))
        pr_lst = reqs["prerequisites"]
        cr_lst = reqs["corequisites"]
        offered = get_terms_offered(course)

        new_course = Course(subject, catalog, offered, pr_lst, cr_lst)
        raw_courselist.append(new_course)

        # append to CSV, writing header only if file is new/empty
        header = ["course", "offered", "prerequisites", "corequisites"]
        need_header = not os.path.exists("courses_learned.csv") or os.stat("courses_learned.csv").st_size == 0
        with open("courses_learned.csv", mode="a", newline="") as wf:
            writer = csv.DictWriter(wf, fieldnames=header)
            if need_header:
                writer.writeheader()
            writer.writerow({
                "course": f"{subject} {catalog}",
                "offered": offered,
                "prerequisites": json.dumps(pr_lst),
                "corequisites": json.dumps(cr_lst),
            })

# We only care about pre/co-reqs that are also in the courselist
glob_courselist = []
for course in raw_courselist:
    current_pr = course.prereqs
    current_cr = course.coreqs
    new_pr = list(filter(lambda x: x in str_courselist, current_pr))
    new_cr = list(filter(lambda x: x in str_courselist, current_cr))
    filtered_course = Course(course.subject, course.catalog, course.offered, new_pr, new_cr)
    glob_courselist.append(filtered_course)

# for course in glob_courselist:
#     print(course.get_info())

valid_configs = []
problem_courses = []

def sort_terms(terms):
    """Sort by year number, then by seasonal order W < S < F. Falls back to lexical."""
    order = {"W": 0, "S": 1, "F": 2}
    def key(t):
        m = re.match(r"([A-Za-z]+)(\d+)$", str(t).strip())
        if not m:
            return (float("inf"), float("inf"), str(t))
        season = m.group(1)[0].upper()
        year = int(m.group(2))
        return (year, order.get(season, 99), str(t))
    return sorted(terms, key=key)

def validate_config(config):
    '''
    Given a config, return True if this criteria is satisfied, else False:
        1. Each term has between 3-5 courses (inclusive)
        2. Each course is actually offered in the term suggested by the config
        3. Each course comes after their prereqs, and either after or alongside their coreqs
    '''
    global problem_courses

    # First ensure each term has at least 3 & at most 5 courses
    szn_counts = Counter(config)
    if any(v < 3 or v > 5 for v in szn_counts.values()):
        return False
    
    # Ensure course is offered the term indicated by the configuration
    for i in range(len(config)):
        if config[i][0] not in glob_courselist[i].offered:
            return False
        
    # Finally ensure courses don't come before/during their prereqs, and that their coreqs don't come after
    for i in range(len(glob_courselist)):
        current_course = glob_courselist[i]

        # Corequisites
        if current_course.coreqs:
            for coreq in current_course.coreqs:
                coreq_pos = str_courselist.index(coreq)
                if ordered_termlist.index(config[coreq_pos]) > ordered_termlist.index(config[i]):
                    return False
                
        # Prerequisites
        if current_course.prereqs:
            for prereq in current_course.prereqs:
                prereq_pos = str_courselist.index(prereq)
                if ordered_termlist.index(config[prereq_pos]) >= ordered_termlist.index(config[i]): # if prereq index >= current course index, thats invalid
                    return False
                
    # Whats not false, must be true
    return True

def organize_config(config):
    '''
    Given a valid course configuration, create an organized dict with (key, value) 
    pairs of (term: Str, courses: List[Course]) and append it to valid_configs.
    '''
    global v
    global valid_configs

    courses_dict = {}
    for i in range(len(config)):
        if config[i] in courses_dict:
            courses_dict[config[i]] += [glob_courselist[i]]
        else:
            courses_dict[config[i]] = [glob_courselist[i]]
    for key in courses_dict:
        courses_dict[key] = [str(course) for course in courses_dict[key]]
    courses_dict_sorted = dict(sorted(courses_dict.items(), key=lambda kv: kv[0][1]))
    v += 1
    valid_configs.append(courses_dict_sorted)

def test_configs(courselist, config=[]):
    global c

    W_count = termlist.count('W')
    S_count = termlist.count('S')
    F_count = termlist.count('F')

    if len(config) == len(courselist):
        if validate_config(config):
            return organize_config(config)
    else:
        curr_course_offered = courselist[len(config)].offered
        for i in range(len(curr_course_offered)):
            if curr_course_offered[i] == 'F':
                for j in range(F_count):
                    test_configs(courselist, config + [courselist[len(config)].offered[i] + str(j+1)])
            if curr_course_offered[i] == 'W':
                for j in range(W_count):
                    test_configs(courselist, config + [courselist[len(config)].offered[i] + str(j+1)])
            if curr_course_offered[i] == 'S':
                for j in range(S_count):
                    test_configs(courselist, config + [courselist[len(config)].offered[i] + str(j+1)])

test_configs(glob_courselist)

### -------------- GUI ------------------

class OutlineItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # Prepare style option and suppress default text painting
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        # Draw outlined text (black outline, white fill)
        painter.save()
        painter.setRenderHint(painter.Antialiasing, True)
        align = getattr(opt, 'displayAlignment', Qt.AlignLeft | Qt.AlignVCenter)
        # Outline
        painter.setPen(QColor("black"))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    painter.drawText(opt.rect.adjusted(dx, dy, dx, dy), align, text)
        # Fill
        painter.setPen(QColor("white"))
        painter.drawText(opt.rect, align, text)
        painter.restore()

class FilterRow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)

        self.term = QLineEdit()
        self.term.setPlaceholderText("Term (e.g. W1)")

        self.kind = QComboBox()
        self.kind.addItems(["Contains", "Not Contains", "Count is"])  # filter type

        self.course = QLineEdit()
        self.course.setPlaceholderText("Course (e.g. CS 370)")

        self.count_label = QLabel("Count:")
        self.count = QSpinBox()
        self.count.setRange(0, 10)
        self.count.setValue(4)

        self.remove_btn = QToolButton()
        self.remove_btn.setText("✖")
        self.remove_btn.setToolTip("Remove this filter")

        row.addWidget(QLabel("Term:"))
        row.addWidget(self.term)
        row.addWidget(self.kind)
        row.addWidget(self.course)
        row.addWidget(self.count_label)
        row.addWidget(self.count)
        row.addStretch(1)
        row.addWidget(self.remove_btn)

        # show/hide appropriate inputs for the selected kind
        self.kind.currentTextChanged.connect(self._on_kind_change)
        self._on_kind_change(self.kind.currentText())

    def _on_kind_change(self, text):
        is_count = (text == "Count is")
        self.course.setVisible(not is_count)
        self.count.setVisible(is_count)
        self.count_label.setVisible(is_count)

    def spec(self):
        """Return a tuple describing this filter, or None if incomplete.
        Types: ("contains", term, course), ("not_contains", term, course), ("count_eq", term, n)
        """
        term = self.term.text().strip()
        if not term:
            return None
        kind = self.kind.currentText()
        if kind in ("Contains", "Not Contains"):
            course = self.course.text().strip()
            if not course:
                return None
            return ("contains" if kind == "Contains" else "not_contains", term, course)
        else:
            return ("count_eq", term, int(self.count.value()))

class ScheduleViewer(QWidget):
    def __init__(self, data_list):
        super().__init__()
        self.setWindowTitle("Course Schedule Viewer")
        self.data_list = data_list
        self.filtered_data = data_list

        layout = QVBoxLayout(self)

        self.setStyleSheet(
            """
            QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QToolButton { color: white; }
            QHeaderView::section { color: white; }
            QTableWidgetItem { margin: 10px; }
            """
        )

        # Filter builder (stackable)
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Filters:"))

        self.add_filter_btn = QPushButton("+")
        self.add_filter_btn.setToolTip("Add a filter")
        self.add_filter_btn.clicked.connect(self.add_filter_row)
        controls_layout.addWidget(self.add_filter_btn)

        controls_layout.addStretch(1)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.apply_filters)
        controls_layout.addWidget(apply_btn)

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self.reset_filters)
        controls_layout.addWidget(reset_btn)

        layout.addLayout(controls_layout)

        self.filters_container = QVBoxLayout()
        layout.addLayout(self.filters_container)
        self.filter_rows = []
        self.add_filter_row()  # start with one row

        # Count label
        self.count_label = QLabel("")
        layout.addWidget(self.count_label)

        # Scroll area for schedules
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll)

        self.populate_tables()

    def populate_tables(self):
        # Clear old content
        for i in reversed(range(self.scroll_layout.count())):
            widget = self.scroll_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        # Count label
        self.count_label.setText(f"Schedules shown: {len(self.filtered_data)}")

        # Add new tables
        for idx, schedule in enumerate(self.filtered_data, start=1):
            table = self.create_table(schedule)
            self.scroll_layout.addWidget(QLabel(f"--- Schedule {idx} ---"))
            self.scroll_layout.addWidget(table)

    def create_table(self, schedule):
        terms = sort_terms(schedule.keys())
        max_courses = max(len(courses) for courses in schedule.values())

        table = QTableWidget()
        table.setRowCount(max_courses)
        table.setColumnCount(len(terms))
        table.setHorizontalHeaderLabels(terms)

        # Use custom delegate for outlined text
        table.setItemDelegate(OutlineItemDelegate(table))

        for col, term in enumerate(terms):
            for row, course in enumerate(schedule[term]):
                item = QTableWidgetItem(course)
                # Background color coding
                cu = course.upper()
                if cu.startswith("PHYS"):
                    item.setBackground(QBrush(QColor("blue")))
                elif cu.startswith("AMATH"):
                    item.setBackground(QBrush(QColor("red")))
                elif cu.startswith("CS"):
                    item.setBackground(QBrush(QColor("white")))
                table.setItem(row, col, item)

        # Make the table expand to exactly fit its contents (no inner scrollbars)
        table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.resizeColumnsToContents()
        table.resizeRowsToContents()

        # Compute and set a fixed size that shows everything
        width = table.verticalHeader().width()
        for c in range(table.columnCount()):
            width += table.columnWidth(c)
        width += table.frameWidth() * 2 + 2

        height = table.horizontalHeader().height()
        for r in range(table.rowCount()):
            height += table.rowHeight(r)
        height += table.frameWidth() * 2 + 2

        table.setFixedSize(width, height)
        return table

    def add_filter_row(self):
        row = FilterRow(self)
        row.remove_btn.clicked.connect(lambda: self.remove_filter_row(row))
        self.filter_rows.append(row)
        self.filters_container.addWidget(row)

    def remove_filter_row(self, row):
        if row in self.filter_rows:
            self.filter_rows.remove(row)
            row.setParent(None)
            row.deleteLater()

    def apply_filters(self):
        specs = []
        for r in self.filter_rows:
            s = r.spec()
            if s is not None:
                specs.append(s)

        def match(schedule, specs):
            for typ, term, val in specs:
                courses = schedule.get(term, [])
                if typ == "contains" and val not in courses:
                    return False
                if typ == "not_contains" and val in courses:
                    return False
                if typ == "count_eq" and len(courses) != int(val):
                    return False
            return True

        if specs:
            self.filtered_data = [sch for sch in self.data_list if match(sch, specs)]
        else:
            self.filtered_data = self.data_list
        self.populate_tables()

    def reset_filters(self):
        self.filtered_data = self.data_list
        self.populate_tables()

if __name__ == "__main__":
    data = valid_configs

    app = QApplication(sys.argv)
    viewer = ScheduleViewer(data)
    viewer.resize(800, 600)
    viewer.show()
    sys.exit(app.exec_())