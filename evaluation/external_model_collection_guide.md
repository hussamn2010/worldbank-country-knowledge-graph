# External Model Collection Guide

Use this guide to add real closed-book answers from Gemini, Claude, DeepSeek, or another model family. Do not give the model project files, the World Bank snapshot, the expected answers, web search, or tools.

## Collection Rules

1. Start a fresh chat with the target model.
2. Disable browsing, search, tools, file access, and connectors when the tool allows it.
3. Paste the batch prompt below unchanged.
4. Save the returned JSON exactly in `model_answers.json` under the correct model key.
5. Add the exact model label, date, access mode, and transcript/run reference to `model_provenance` when available.
6. Run `& ".\.venv\Scripts\python.exe" ".\evaluate_project.py" --output-dir ".\evaluation"` to rescore.

## Batch Prompt

```text
You are participating in a closed-book benchmark. Do not browse the web, use tools, inspect files, or access external data. Answer from your own knowledge only. Return ONLY one valid JSON object with exactly the following keys. Use a short text value, a JSON array, or a number as requested. Do not add Markdown or explanations.

capital_target: What is the capital city of Pakistan? Return one short text value.
region_target: Which World Bank region contains Pakistan? Return the official World Bank label.
income_target: What is the World Bank income level of Pakistan? Return the official label.
region_members: List every country in the World Bank region 'South Asia'. Return a JSON list of country names with no explanation.
rule_similar: Using the rule 'same World Bank region and same income level', list every country similar to Pakistan. Return a JSON list of country names with no explanation.
explainable_top_three: Using weights region=0.30, income=0.25, GDP-per-capita=0.20, life-expectancy=0.15, population=0.10, list the top three countries most similar to Pakistan. Return a JSON list of country names with no explanation.
population_over_100m: List every represented country with population at least 100000000. Return a JSON list of country names with no explanation.
health_outliers_above: For each income group, compute average life expectancy and select countries at least 3.0 years above their group average. Return the first five country names ranked by absolute difference.
population_target: What is the latest population value for Pakistan? Return only a number.
gdp_target: What is the latest GDP per capita in current US dollars for Pakistan? Return only a number.
life_expectancy_target: What is the latest life expectancy value for Pakistan? Return only a number.
```

A model is scored only after all 11 real answers are recorded. Pending answers are not treated as zero scores.
