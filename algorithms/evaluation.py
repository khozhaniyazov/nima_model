def evaluate_with_gpt4(code: str, video_path: str, prompt: str, execution_data: dict) -> dict:
    
    evaluation_prompt = f"""You are an expert educational video evaluator. Analyze this Manim animation.

**Original Request:** {prompt}

**Execution Data:**
- Render Status: {execution_data['status']}
- Duration: {execution_data.get('duration', 'N/A')}s
- Errors: {execution_data.get('error', 'None')}

**Generated Code Preview:**
```python
{code[:1000]}...
```

Evaluate on these dimensions (0-100 each):

1. **Visual Quality** - Layout, colors, clarity, no overlaps
2. **Educational Value** - Clear explanations, good examples
3. **Technical Accuracy** - Correct math/science, no errors
4. **Pacing & Timing** - Appropriate speed, good wait times
5. **Clarity** - Easy to understand, well-organized
6. **Engagement** - Interesting, dynamic, not boring

Also provide:
- **Strengths:** What worked well (bullet points)
- **Weaknesses:** What needs improvement (bullet points)
- **Specific Issues:** Technical problems found
- **Suggestions:** How to improve
- **Predicted User Satisfaction:** (0-100)

Respond in JSON format:
```json
{
  "visual_quality": 85,
  "educational_value": 90,
  "technical_accuracy": 80,
  "pacing_timing": 75,
  "clarity": 88,
  "engagement": 82,
  "overall": 83,
  "strengths": ["point 1", "point 2"],
  "weaknesses": ["point 1", "point 2"],
  "issues": ["issue 1", "issue 2"],
  "suggestions": "Suggestions text...",
  "predicted_satisfaction": 85
}
```
"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an educational video quality evaluator."},
                {"role": "user", "content": evaluation_prompt}
            ],
            temperature=0.3
        )
        
        result_text = response.choices[0].message.content
        
        if "```json" in result_text:
            json_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            json_text = result_text.split("```")[1].split("```")[0].strip()
        else:
            json_text = result_text
        
        evaluation = json.loads(json_text)
        return evaluation
        
    except Exception as e:
        print(f"[EVAL] Error: {str(e)}")
        return {
            "overall": 0,
            "error": str(e)
        }