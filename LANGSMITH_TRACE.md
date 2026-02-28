# LangSmith Trace

Link to the full reasoning loop: detectives collecting evidence → judges arguing → Chief Justice synthesizing the verdict.

**Trace URL:** [Add your LangSmith trace URL here](https://smith.langchain.com/)

---

To generate a trace:

1. Set `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` in `.env`
2. Run the auditor: `python -m src.run_audit --repo-url . --pdf-path reports/final_report.pdf`
3. Open your [LangSmith](https://smith.langchain.com/) project and copy the run URL
4. Replace the placeholder above with your trace URL
