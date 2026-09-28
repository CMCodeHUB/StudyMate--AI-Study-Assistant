
import warnings

# Hide the Gemini automatic function calling warning
warnings.filterwarnings(
    "ignore",
    message="Direct use of automatic function calling"
)

"""
StudyMate — AI Study Planning Agent

Features:
1. RAG-based answers from study notes
2. Gemini fallback for general academic questions
3. Study task management using SQLite
4. LangGraph-based routing
5. Short-term conversation history
"""

import os
import glob
from typing import TypedDict, List, Literal, Optional

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

import db


# ---------------------------------------------------------------------------
# 1. Agent State
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    user_input: str
    intent: Literal["notes", "general", "task", "chat"]
    chat_history: List[str]
    response: str
    user_id: Optional[int]  # signed-in web user; None for the CLI


# ---------------------------------------------------------------------------
# 2. Build RAG Vector Store
# ---------------------------------------------------------------------------

def build_vector_store():
    docs = []

    note_files = glob.glob(
        os.path.join("sample_notes", "*.txt")
    )

    for path in note_files:
        docs.extend(
            TextLoader(
                path,
                encoding="utf-8"
            ).load()
        )

    if not docs:
        print("Warning: No study notes found in sample_notes/")
        return None

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=350,
        chunk_overlap=50
    )

    chunks = splitter.split_documents(docs)

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )

    return FAISS.from_documents(
        chunks,
        embeddings
    )


vector_store = build_vector_store()


# ---------------------------------------------------------------------------
# 3. Gemini Model
# ---------------------------------------------------------------------------

llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite"
)


# ---------------------------------------------------------------------------
# 4. Safely extract text from Gemini response
# ---------------------------------------------------------------------------

def get_text(result) -> str:
    """
    Safely extract plain text from an LLM response.
    Supports both string and block-based content.
    """

    content = result.content

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []

        for block in content:

            if isinstance(block, str):
                parts.append(block)

            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])

        return "".join(parts).strip()

    return str(content).strip()


# ---------------------------------------------------------------------------
# 5. Intent Classification
# ---------------------------------------------------------------------------

def classify_intent(state: AgentState) -> AgentState:

    prompt = (
        "Classify the user's message into exactly one word:\n\n"

        "'notes' = conceptual, educational, programming, academic, "
        "or study-related question.\n"

        "'task' = adding, completing, deleting, or listing study tasks.\n"

        "'chat' = casual conversation or anything unrelated to studying.\n\n"

        "Reply with ONLY one word: notes, task, or chat.\n\n"

        f"Message: {state['user_input']}"
    )

    result = llm.invoke(
        [HumanMessage(content=prompt)]
    )

    intent = get_text(result).lower().strip()

    if intent not in {"notes", "task", "chat"}:
        intent = "chat"

    state["intent"] = intent

    return state


# ---------------------------------------------------------------------------
# 6. Route
# ---------------------------------------------------------------------------

def route(state: AgentState) -> str:
    return state["intent"]


# ---------------------------------------------------------------------------
# 7. Answer From Notes + Gemini Fallback
# ---------------------------------------------------------------------------

def answer_from_notes(state: AgentState) -> AgentState:

    question = state["user_input"]

    # If vector store is unavailable, directly use Gemini
    if vector_store is None:
        prompt = (
            "You are StudyMate, a helpful AI study assistant.\n"
            "Answer the student's question clearly and accurately.\n"
            "Use simple explanations and examples when helpful.\n\n"
            f"Question: {question}"
        )

        result = llm.invoke(
            [HumanMessage(content=prompt)]
        )

        state["response"] = get_text(result)
        state["intent"] = "general"

        return state

    # -------------------------------------------------------
    # Search the study notes
    # -------------------------------------------------------

    docs_with_scores = vector_store.similarity_search_with_score(
        question,
        k=3
    )

    # FAISS distance:
    # Smaller distance = more similar
    #
    # We use a simple threshold so unrelated questions
    # don't get incorrectly answered from unrelated notes.

    relevant_docs = [
        doc
        for doc, score in docs_with_scores
        if score < 1.20
    ]

    # -------------------------------------------------------
    # CASE 1: Relevant notes found
    # -------------------------------------------------------

    if relevant_docs:

        context = "\n\n".join(
            doc.page_content
            for doc in relevant_docs
        )

        prompt = (
            "You are StudyMate, an AI study assistant.\n\n"

            "Answer the student's question using the study notes "
            "provided below.\n\n"

            "If the notes contain the answer, explain it clearly "
            "and concisely.\n\n"

            "Do not mention the internal retrieval system.\n\n"

            f"Study Notes:\n{context}\n\n"

            f"Question:\n{question}"
        )

        result = llm.invoke(
            [HumanMessage(content=prompt)]
        )

        state["response"] = get_text(result)

        return state

    # -------------------------------------------------------
    # CASE 2: No relevant notes → Gemini fallback
    # -------------------------------------------------------

    prompt = (
        "You are StudyMate, a helpful AI study assistant.\n\n"

        "The student's question was not found in the available "
        "study notes.\n\n"

        "Answer the question using your general knowledge.\n\n"

        "Give a clear, accurate and student-friendly explanation.\n"

        "For programming questions, include examples when useful.\n"

        "Do not say that the answer is missing from the notes.\n"

        f"\nQuestion:\n{question}"
    )

    result = llm.invoke(
        [HumanMessage(content=prompt)]
    )

    state["response"] = get_text(result)
    state["intent"] = "general"  # correctly label as general knowledge, not notes

    return state


# ---------------------------------------------------------------------------
# 8. Study Task Management
# ---------------------------------------------------------------------------

def manage_task(state: AgentState) -> AgentState:

    prompt = (
        "The user wants to manage a study task.\n\n"

        "Reply with ONLY one line in this format:\n"

        "ACTION|VALUE\n\n"

        "ACTION must be one of:\n"
        "ADD\n"
        "DONE\n"
        "LIST\n\n"

        "For ADD, VALUE should be the task topic.\n"
        "For DONE, VALUE should be the task ID.\n"
        "For LIST, VALUE should be empty.\n\n"

        f"Message: {state['user_input']}"
    )

    result = llm.invoke(
        [HumanMessage(content=prompt)]
    )

    try:
        action, value = get_text(result).split("|", 1)

    except ValueError:
        action, value = "LIST", ""

    action = action.strip().upper()
    value = value.strip()

    # -------------------------------------------------------
    # ADD TASK
    # -------------------------------------------------------

    user_id = state.get("user_id")

    if action == "ADD" and value:

        task_id = db.add_task(value, user_id)

        state["response"] = (
            f"Added task #{task_id}: {value}"
        )

        return state

    # -------------------------------------------------------
    # MARK TASK DONE
    # -------------------------------------------------------

    elif action == "DONE" and value.isdigit():

        ok = db.complete_task(
            int(value),
            user_id
        )

        if ok:
            state["response"] = (
                f"Marked task #{value} as done."
            )

        else:
            state["response"] = (
                f"No task with id {value}."
            )

        return state

    # -------------------------------------------------------
    # LIST TASKS
    # -------------------------------------------------------

    rows = db.list_tasks(user_id=user_id)

    if not rows:

        state["response"] = (
            "No study tasks yet.\n"
            "Try: 'Add a task to revise linked lists'."
        )

    else:

        lines = [
            f"#{r[0]} [{r[2]}] {r[1]}"
            for r in rows
        ]

        state["response"] = (
            "Your study tasks:\n"
            + "\n".join(lines)
        )

    return state


# ---------------------------------------------------------------------------
# 9. General Chat Response
# ---------------------------------------------------------------------------

def general_response(state: AgentState) -> AgentState:

    prompt = (
        "You are StudyMate, a friendly AI study assistant.\n"
        "Answer the user naturally and helpfully.\n\n"
        f"User: {state['user_input']}"
    )

    result = llm.invoke(
        [HumanMessage(content=prompt)]
    )

    state["response"] = get_text(result)

    return state


# ---------------------------------------------------------------------------
# 10. Build LangGraph
# ---------------------------------------------------------------------------

graph = StateGraph(AgentState)

graph.add_node(
    "classify_intent",
    classify_intent
)

graph.add_node(
    "answer_from_notes",
    answer_from_notes
)

graph.add_node(
    "manage_task",
    manage_task
)

graph.add_node(
    "general_response",
    general_response
)


graph.set_entry_point(
    "classify_intent"
)


graph.add_conditional_edges(
    "classify_intent",
    route,
    {
        "notes": "answer_from_notes",
        "task": "manage_task",
        "chat": "general_response"
    }
)


graph.add_edge(
    "answer_from_notes",
    END
)

graph.add_edge(
    "manage_task",
    END
)

graph.add_edge(
    "general_response",
    END
)


app = graph.compile()


# ---------------------------------------------------------------------------
# 11. CLI Application
# ---------------------------------------------------------------------------

def main():

    print("\n======================================")
    print("        StudyMate AI Agent")
    print("======================================\n")

    print("StudyMate agent ready. Try things like:")

    print(" - 'What is polymorphism?'")
    print(" - 'What is Python?'")
    print(" - 'Explain recursion'")
    print(" - 'Add a task to revise hash maps'")
    print(" - 'List my tasks'")

    print("\nType 'exit' to quit.\n")

    history: List[str] = []

    while True:

        user_input = input("You: ").strip()

        if user_input.lower() in {
            "exit",
            "quit"
        }:
            print("\nGoodbye! Keep learning. \U0001f680")
            break

        if not user_input:
            continue

        try:

            result = app.invoke(
                {
                    "user_input": user_input,
                    "intent": "chat",
                    "chat_history": history,
                    "response": ""
                }
            )

            print(
                f"\nStudyMate [{result['intent']}]: "
                f"{result['response']}\n"
            )

            history.append(user_input)

        except Exception as e:

            print(
                "\nStudyMate [error]: "
                f"{str(e)}\n"
            )


# ---------------------------------------------------------------------------
# 12. Start Application
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
