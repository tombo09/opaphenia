from openai import OpenAI
from fastapi import HTTPException

client = OpenAI()

def moderate_text(text: str):
    resp = client.moderations.create(
        model="omni-moderation-latest",
        input=text,
    )
    result = resp.results[0]
    return {
        "flagged": result.flagged,
        "categories": result.categories,
        "scores": result.category_scores,
    }