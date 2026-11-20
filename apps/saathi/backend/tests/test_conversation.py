from agents_core.llm import LLMProvider
from agents_core.llm.testing import ScriptedLLM

from saathi.agent import Agent, InMemorySessionStore
from saathi.agent.conversation import FALLBACK_REPLY
from saathi.config import Settings
from saathi.schemes import load_schemes

SCHEMES = load_schemes(Settings().schemes_dir)


def make_agent(llm, **kwargs) -> Agent:
    return Agent(llm, SCHEMES, InMemorySessionStore(), **kwargs)


async def test_first_turn_updates_profile_and_asks_one_question():
    llm = ScriptedLLM(
        [{"language": "Hindi (Devanagari script)", "updates": {"age": 32, "occupation": "farmer"}, "intent": "provide_info"}]
    )
    agent = make_agent(llm)

    reply = await agent.handle("u1", "मैं 32 साल का किसान हूँ")

    assert reply == "REPLY"
    assert (await agent.profile("u1")).age == 32
    prompt = llm.text_prompts()[0]
    assert "Reply in Hindi (Devanagari script)" in prompt
    assert "free" in prompt and "ask exactly ONE question" in prompt


async def test_shows_results_once_nothing_left_to_ask():
    llm = ScriptedLLM(
        [
            {
                "language": "English",
                "updates": {
                    "age": 32, "gender": "male", "occupation": "farmer", "has_bank_account": True,
                    "owns_cultivable_land": True, "is_income_tax_payer": False,
                    "is_government_employee": False, "plans_new_business": False,
                    "is_studying_post_matric": False, "is_bpl": False,
                    "is_widow": False, "has_disability": False, "is_pregnant_or_lactating": False,
                    "residence": "rural", "ration_card": "none", "has_pucca_house": True,
                    "has_lpg_connection": True, "land_holding_hectares": 1.0, "has_epf_esic_or_nps": False,
                },
            }
        ]
    )  # fmt: skip
    agent = make_agent(llm)

    await agent.handle("u1", "...")

    prompt = llm.text_prompts()[0]
    assert "SCHEME DATA" in prompt
    assert "PM-KISAN" in prompt
    assert "Stand-Up India" not in prompt


async def test_show_results_intent_skips_remaining_questions():
    llm = ScriptedLLM([{"language": "English", "updates": {"age": 30}, "intent": "show_results"}])
    agent = make_agent(llm)

    await agent.handle("u1", "just show me what I can get")

    assert "SCHEME DATA" in llm.text_prompts()[0]


async def test_declined_field_is_not_asked_again():
    llm = ScriptedLLM([{"language": "English", "unknown_fields": ["age"]}])
    agent = make_agent(llm)

    await agent.handle("u1", "I don't know my age")

    assert "How old are you?" not in llm.text_prompts()[0]


async def test_invalid_values_from_llm_are_ignored():
    llm = ScriptedLLM([{"updates": {"age": -4, "state": "Atlantis", "aadhaar": "1234", "gender": "female"}}])
    agent = make_agent(llm)

    await agent.handle("u1", "...")

    profile = (await agent.profile("u1"))
    assert profile.age is None and profile.state is None
    assert profile.gender == "female"


async def test_identity_numbers_never_reach_the_llm():
    llm = ScriptedLLM([{}])
    agent = make_agent(llm)

    await agent.handle("u1", "my aadhaar is 2345 6789 0123 and phone 9876543210")

    sent = " ".join(m.content for msgs, _ in llm.calls for m in msgs)
    assert "2345 6789 0123" not in sent and "9876543210" not in sent


async def test_delete_data_clears_session():
    llm = ScriptedLLM([{"updates": {"age": 30}}, {"intent": "delete_data"}])
    agent = make_agent(llm)

    await agent.handle("u1", "I am 30")
    await agent.handle("u1", "delete my data")

    assert (await agent.profile("u1")).age is None


async def test_stops_asking_after_question_budget():
    llm = ScriptedLLM([{}, {}])
    agent = make_agent(llm, max_questions=1)

    await agent.handle("u1", "hi")
    await agent.handle("u1", "hmm")

    first, second = llm.text_prompts()
    assert "ask exactly ONE question" in first
    assert "SCHEME DATA" in second


async def test_provider_failure_returns_fallback():
    class Broken(LLMProvider):
        name = "broken"

        async def complete(self, messages, *, json_output=False):
            raise ConnectionError("down")

    assert await make_agent(Broken()).handle("u1", "hi") == FALLBACK_REPLY

