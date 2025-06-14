from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .mongo_client import collection
from .rag_client import rag_db_manager  # Change here
import json
import re
import uuid
import os

TREE_PATH = os.path.join(os.path.dirname(__file__), 'question_tree.json')
with open(TREE_PATH, 'r') as f:
    QUESTION_TREE = json.load(f)

def chatbot_form(request):
    return render(request, "chat.html")

@csrf_exempt
def chatbot_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST method allowed"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    action = data.get("action", "")
    uid = data.get("uid")
    name = data.get("name", "").strip()
    contact = data.get("contact", "").strip()
    email = data.get("email", "").strip()
    field_selected = data.get("field", "").lower()
    current_index = data.get("question_index", 0)

    session = request.session

    if action == "name":
        if not name:
            return JsonResponse({"error": "Name is required"}, status=400)
        generated_uid = str(uuid.uuid4())
        user_data = {"uid": generated_uid, "name": name}
        collection.insert_one(user_data)
        session["uid"] = generated_uid
        session["name"] = name
        session["answers"] = {}
        session["field"] = None
        session["contact"] = None
        session["email"] = None
        session.modified = True
        return JsonResponse({"message": f"Hi {name}!", "uid": generated_uid})

    elif action == "contact":
        if not (uid and contact):
            return JsonResponse({"error": "Missing uid or contact"}, status=400)
        if not re.match(r'^(\+94\d{9}|0\d{9})$', contact):
            return JsonResponse({"error": "Invalid contact number"}, status=400)
        collection.update_one({"uid": uid}, {"$set": {"contact": contact}})
        session["contact"] = contact
        session.modified = True
        return JsonResponse({"message": "Contact saved!"})

    elif action == "email":
        if not (uid and email):
            return JsonResponse({"error": "Missing uid or email"}, status=400)
        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
            return JsonResponse({"error": "Invalid email address"}, status=400)
        collection.update_one({"uid": uid}, {"$set": {"email": email}})
        session["email"] = email
        session.modified = True
        buttons = [
            {"title": "Agriculture", "payload": "agriculture"},
            {"title": "Transport", "payload": "transport"},
            {"title": "Tourism", "payload": "tourism"}
        ]
        return JsonResponse({"message": "What is your field?", "buttons": buttons})

    elif action == "field":
        if not (uid and field_selected):
            return JsonResponse({"error": "Missing uid or field"}, status=400)
        if field_selected not in QUESTION_TREE:
            return JsonResponse({"error": "Invalid field selected"}, status=400)
        collection.update_one({"uid": uid}, {"$set": {"field": field_selected}})
        session["field"] = field_selected
        session.modified = True
        first_question = QUESTION_TREE[field_selected][0]
        return JsonResponse({
            "message": f"Thank you! You selected '{field_selected.capitalize()}'. Let's begin.",
            "field": field_selected,
            "uid": uid,
            "next_action": "field_questions",
            "question_index": 1,
            "question": first_question["question"],
            "question_id": first_question["id"],
            "type": first_question["type"],
            "options": first_question.get("options", [])
        })

    elif action == "field_questions":
        answer = data.get("answer")
        question_id = data.get("question_id")
        field_selected = session.get("field") or field_selected
        questions = QUESTION_TREE.get(field_selected, [])
        if uid != session.get("uid"):
            return JsonResponse({"error": "Session/uid mismatch"}, status=400)
        if answer is not None and question_id is not None:
            question_obj = next((q for q in questions if q["id"] == question_id), None)
            if question_obj:
                question_text = question_obj["question"]
                answers = session.get("answers", {})
                answers[question_text] = answer
                session["answers"] = answers
                session.modified = True

        if current_index >= len(questions):
            user_json = {
                "uid": session["uid"],
                "name": session.get("name"),
                "contact": session.get("contact"),
                "email": session.get("email"),
                "field": session.get("field"),
                "answers": session.get("answers", {})
            }
            # Save to user's own RAG DB (by company name, uid, and field)
            company_name = session.get("name") or "Unknown"
            field_val = session.get("field")
            user_db = rag_db_manager.get_user_db(company_name, session["uid"], field_val)
            user_db.add_json(user_json)
            if "answers" in session:
                del session["answers"]
            session.modified = True
            return JsonResponse({
                "message": "All questions have been completed. Thank you!"
            })

        question = questions[current_index]
        return JsonResponse({
            "question_index": current_index + 1,
            "question": question["question"],
            "question_id": question["id"],
            "type": question["type"],
            "options": question.get("options", []),
            "next_action": "field_questions"
        })

    else:
        return JsonResponse({"error": "Unknown action"}, status=400)