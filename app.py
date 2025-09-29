import os
import re
import json
import unicodedata
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, session, flash
from openai import OpenAI
import docx
import PyPDF2

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "supersecretkey")

# OpenAI ключ - только из переменных окружения
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "not free")
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ----------------- пользователи и роли -----------------
USERS = {
    "teacher": {"password": "1234", "role": "teacher"},
    "student": {"password": "0000", "role": "student"}
}

# файлы для хранения тестов и результатов
TEST_FILE = "tests.json"
RESULTS_FILE = "results.json"

# ----------------- утилиты -----------------
def normalize_text(s: str) -> str:
    """Улучшенная нормализация текста"""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.replace("\u00A0", " ").replace("\u200B", "")
    s = re.sub(r'[^\w\s]', ' ', s, flags=re.UNICODE)
    s = re.sub(r'\s+', ' ', s)
    return s.strip().lower()

def validate_test_params(form_data):
    """Валидация параметров теста"""
    try:
        num_questions = max(1, min(20, int(form_data.get("num_questions", 5))))
        num_options = max(2, min(10, int(form_data.get("num_options", 4))))
        num_correct = max(1, min(5, int(form_data.get("num_correct", 1))))
        num_incorrect = max(1, min(10, int(form_data.get("num_incorrect", 3))))
        return num_questions, num_options, num_correct, num_incorrect
    except (ValueError, TypeError):
        return 5, 4, 1, 3  # значения по умолчанию при ошибке

def extract_text_from_file(filepath: str) -> str:
    """Извлечение текста из файла с улучшенной обработкой ошибок"""
    ext = filepath.split(".")[-1].lower()
    text = ""
    try:
        if ext == "txt":
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        elif ext == "pdf":
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    p = page.extract_text()
                    if p:
                        text += p + "\n"
        elif ext == "docx":
            doc = docx.Document(filepath)
            for para in doc.paragraphs:
                text += para.text + "\n"
    except Exception as e:
        print(f"Ошибка при чтении файла {filepath}: {e}")
        flash(f"Ошибка чтения файла: {e}", "danger")
    return text.strip()

def load_tests():
    """Загрузка тестов из файла"""
    if not os.path.exists(TEST_FILE):
        return []
    try:
        with open(TEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("Ошибка чтения tests.json:", e)
        return []

def save_tests(tests):
    """Сохранение тестов в файл"""
    try:
        with open(TEST_FILE, "w", encoding="utf-8") as f:
            json.dump(tests, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Ошибка записи tests.json:", e)
        flash("Ошибка сохранения теста", "danger")

def load_results():
    """Загрузка результатов тестирования"""
    if not os.path.exists(RESULTS_FILE):
        return []
    try:
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("Ошибка чтения results.json:", e)
        return []

def save_result(username, student_name, score, results, total_questions, test_data):
    """Сохранение результата тестирования"""
    try:
        existing_results = load_results()
        
        # Используем имя студента, если оно указано
        display_name = student_name if student_name and student_name.strip() else username
        
        result_data = {
            "id": len(existing_results) + 1,
            "username": username,
            "student_name": display_name,
            "timestamp": datetime.now().isoformat(),
            "score": score,
            "total_questions": total_questions,
            "percentage": round((score / total_questions) * 100, 2) if total_questions > 0 else 0,
            "results": results,
            "test_metadata": test_data
        }
        
        existing_results.append(result_data)
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing_results, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Ошибка сохранения результата:", e)

def advanced_text_comparison(user_answer, correct_answers):
    """Улучшенное сравнение текстовых ответов"""
    if not user_answer or not correct_answers:
        return False
    
    user_normalized = normalize_text(user_answer)
    
    for correct in correct_answers:
        if not correct:
            continue
        correct_normalized = normalize_text(correct)
        
        # Проверка на полное совпадение или включение
        if (user_normalized == correct_normalized or 
            correct_normalized in user_normalized or
            user_normalized in correct_normalized):
            return True
            
        # Проверка на схожесть по словам (если больше 50% совпадают)
        user_words = set(user_normalized.split())
        correct_words = set(correct_normalized.split())
        if len(user_words & correct_words) / max(len(correct_words), 1) > 0.5:
            return True
            
    return False

# ----------------- login / logout -----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = USERS.get(username)
        if user and user["password"] == password:
            session["username"] = username
            session["role"] = user["role"]
            flash(f"Вы вошли как {user['role']}", "success")
            if user["role"] == "teacher":
                return redirect(url_for("index"))
            else:
                return redirect(url_for("student_start"))
        return render_template("login.html", error="Неверный логин или пароль")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из системы", "info")
    return redirect(url_for("login"))

# ----------------- стартовая страница для студента -----------------
@app.route("/student_start", methods=["GET", "POST"])
def student_start():
    if request.method == "POST":
        student_name = request.form.get("student_name", "").strip()
        if student_name:
            session["student_name"] = student_name
            session["role"] = "student"   # фикс: назначаем роль
            flash(f"Добро пожаловать, {student_name}!", "success")
            return redirect(url_for("test_page"))
        else:
            flash("Пожалуйста, введите ваше имя", "danger")
    
    return render_template("student_start.html")


# ----------------- index (генерация теста) -----------------
@app.route("/", methods=["GET", "POST"])
def index():
    if session.get("role") != "teacher":
        return redirect(url_for("student_start"))

    if request.method == "POST":
        text = request.form.get("text", "").strip()
        file = request.files.get("file")

        # Валидация параметров
        num_questions, num_options, num_correct, num_incorrect = validate_test_params(request.form)

        if file and file.filename:
            filename = file.filename
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            file_text = extract_text_from_file(filepath)
            if file_text:
                text = (text + "\n" + file_text).strip()

        if not text:
            flash("Ошибка: нет текста для генерации теста.", "danger")
            return redirect(url_for("index"))

        test_type = request.form.get("test_type", "choice")
        difficulty = request.form.get("difficulty", "easy")

        prompt = f"""
        Вот конспект лекции:
        {text}

        Составь тест по этому конспекту:
        - Количество вопросов: {num_questions}
        - Количество вариантов ответа: {num_options}
        - Количество правильных ответов на вопрос: {num_correct}
        - Количество неправильных ответов на вопрос: {num_incorrect}
        - Тип теста: {test_type}
        - Сложность: {difficulty}

        Верни результат строго в формате JSON:
        [
          {{
            "question": "Текст вопроса",
            "options": ["вариант1", "вариант2", "вариант3", ...],
            "answers": ["правильный1", ...],
            "type": "choice"
          }}
        ]
        """

        test_json = []
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                timeout=30
            )
            content = response.choices[0].message.content
            match = re.search(r"\[.*\]", content, re.S)
            if match:
                test_json = json.loads(match.group(0))
            else:
                flash("Ошибка: не удалось распарсить ответ AI", "danger")
                test_json = []
        except Exception as e:
            print("Ошибка при генерации/парсинге от OpenAI:", e)
            flash(f"Ошибка генерации теста: {str(e)}", "danger")
            return redirect(url_for("index"))

        # Нормализация структуры теста
        normalized = []
        for q in test_json:
            question_text = q.get("question") or q.get("question_text") or ""
            qtype = q.get("type", "choice")
            raw_answers = q.get("answers") if "answers" in q else q.get("answer", [])
            if isinstance(raw_answers, str):
                raw_answers = [raw_answers]
            options = q.get("options") if isinstance(q.get("options"), list) else []
            
            normalized.append({
                "question": question_text,
                "type": qtype,
                "answers": [str(x).strip() for x in raw_answers if x is not None and str(x).strip()],
                "options": [str(x).strip() for x in options if x is not None and str(x).strip()]
            })

        session["test"] = normalized
        save_tests(normalized)
        flash("Тест сгенерирован и сохранён.", "success")
        return redirect(url_for("test_page"))

    return render_template("index.html")

# ----------------- прохождение теста -----------------
@app.route("/test", methods=["GET", "POST"])
def test_page():
    # если студент, но не ввёл имя → отправляем на ввод имени
    if session.get("role") == "student" and not session.get("student_name"):
        return redirect(url_for("student_start"))

    # если не студент и не учитель → только тогда на login
    if session.get("role") not in ["teacher", "student"]:
        return redirect(url_for("login"))

    test_json = session.get("test", [])
    if not test_json:
        return "<h3>Тест ещё не сгенерирован.</h3>"

    if request.method == "POST":
        results = []
        score = 0
        for i, q in enumerate(test_json):
            qtype = q.get("type", "choice")
            raw_answers = q.get("answers") or []
            if isinstance(raw_answers, str):
                raw_answers = [raw_answers]
            correct_list = [str(x) for x in raw_answers if x]

            if qtype == "choice":
                user_answers = request.form.getlist(f"q{i}")
                user_answers = [str(x) for x in user_answers if x and str(x).strip() != ""]
                correct_norm = set(normalize_text(a) for a in correct_list)
                user_norm_set = set(normalize_text(a) for a in user_answers)
                score += len(user_norm_set & correct_norm)

                results.append({
                    "question": q.get("question"),
                    "your_answer": user_answers if user_answers else "—",
                    "correct_answer": correct_list
                })
            else:
                user_text = request.form.get(f"q{i}", "").strip()
                found = any(ans and normalize_text(ans) in normalize_text(user_text) for ans in correct_list)
                score += 1 if found else 0
                results.append({
                    "question": q.get("question"),
                    "your_answer": user_text if user_text else "—",
                    "correct_answer": correct_list
                })

        return render_template("result.html", results=results, score=score, total=len(test_json))

    return render_template("test.html", test=test_json)

# ----------------- админка -----------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if session.get("role") != "teacher":
        return redirect(url_for("login"))

    test = session.get("test", [])

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            q = request.form.get("question", "").strip()
            opts = request.form.get("options", "").split("\n")
            answ = request.form.get("answers", "").split("\n")
            qtype = request.form.get("type", "choice")
            
            if q:
                test.append({
                    "question": q,
                    "options": [o.strip() for o in opts if o.strip()],
                    "answers": [a.strip() for a in answ if a.strip()],
                    "type": qtype
                })
                session["test"] = test
                save_tests(test)
                flash("Вопрос добавлен", "success")
            else:
                flash("Вопрос не может быть пустым", "danger")
                
        elif action == "delete":
            idx = int(request.form.get("index", -1))
            if 0 <= idx < len(test):
                test.pop(idx)
                session["test"] = test
                save_tests(test)
                flash("Вопрос удалён", "info")
        elif action == "update":
            idx = int(request.form.get("index", -1))
            if 0 <= idx < len(test):
                test[idx]["question"] = request.form.get("question", "").strip()
                test[idx]["options"] = [o.strip() for o in request.form.get("options", "").split("\n") if o.strip()]
                test[idx]["answers"] = [a.strip() for a in request.form.get("answers", "").split("\n") if a.strip()]
                test[idx]["type"] = request.form.get("type", "choice")
                session["test"] = test
                save_tests(test)
                flash("Вопрос обновлён", "success")

        return redirect(url_for("admin"))

    return render_template("admin.html", test=test)

# ----------------- статистика -----------------
@app.route("/stats")
def stats():
    if session.get("role") != "teacher":
        return redirect(url_for("login"))
    
    results = load_results()
    tests = load_tests()
    
    # Базовая статистика
    total_attempts = len(results)
    average_score = round(sum(r["score"] for r in results) / total_attempts, 2) if total_attempts > 0 else 0
    average_percentage = round(sum(r["percentage"] for r in results) / total_attempts, 2) if total_attempts > 0 else 0
    
    # Поиск сложного вопроса
    question_difficulty = {}
    for result in results:
        for i, q_result in enumerate(result["results"]):
            key = q_result["question"][:50]
            if key not in question_difficulty:
                question_difficulty[key] = {"correct": 0, "total": 0}
            question_difficulty[key]["total"] += 1
            if q_result["is_fully_correct"]:
                question_difficulty[key]["correct"] += 1
    
    hardest_question = "Нет данных"
    min_correct_rate = 1.0
    for q, stats in question_difficulty.items():
        correct_rate = stats["correct"] / stats["total"]
        if correct_rate < min_correct_rate:
            min_correct_rate = correct_rate
            hardest_question = q + "..." if len(q) >= 50 else q

    return render_template(
        "stats.html",
        total_attempts=total_attempts,
        average_score=average_score,
        average_percentage=average_percentage,
        hardest_question=hardest_question,
        hardest_question_rate=round(min_correct_rate * 100, 2),
        recent_results=results[-10:][::-1]
    )

# ----------------- запуск -----------------
if __name__ == "__main__":
    app.run(debug=True)