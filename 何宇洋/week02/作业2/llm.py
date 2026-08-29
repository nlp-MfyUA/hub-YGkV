import os

from dotenv import load_dotenv
from openai import OpenAI

from prompt import SYSTEM_PROMPT
from tools import relationship_tool


load_dotenv()


client = OpenAI(
    api_key=os.getenv(
        "OPENAI_API_KEY"
    ),
    base_url=os.getenv(
        "OPENAI_BASE_URL"
    )
)


def chat(user_input: str):

    response = client.chat.completions.create(
        model=os.getenv(
            "MODEL",
            "deepseek-chat"
        ),

        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": user_input
            }
        ],

        tools=[
            relationship_tool
        ]
    )

    return response.choices[0].message