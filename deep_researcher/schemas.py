from pydantic import BaseModel, Field

class Query(BaseModel):
    query: str =Field(description='实际的搜索词')
    rationale: str = Field(description="为什么这个搜索词相关")


class FollowUpQuery(BaseModel):
    follow_up_query: str = Field(description="追问搜索词")
    knowledge_gap: str = Field(description="总结中缺失的信息")


class UserIntent(BaseModel):
    action: str = Field(
        description=(
            "动作：new_research / continue_research / answer_from_memory / "
            "view / follow_up / recall / exit / unknown"
        )
    )
    researcher_id: str = Field(default="", description="分支编号，如 r1")
    topic: str = Field(default="", description="研究主题")
    query_index: int = Field(default=0, description="追问第几个搜索词，从 1 开始")
    follow_up: str = Field(default="", description="追问内容")
    standalone_query: str = Field(default="", description="补全代词后的独立问题")
    needs_clarification: bool = Field(default=False, description="是否需要反问澄清")
    clarification_question: str = Field(default="", description="反问内容")
    clarification_options: list[str] = Field(
        default_factory=list,
        description="候选主题列表",
    )


class ClarificationChoice(BaseModel):
    resolved: bool = Field(description="是否已经确定用户指向哪个分支")
    researcher_id: str = Field(default="", description="选中的分支编号")
    standalone_query: str = Field(default="", description="补全后的独立问题")
    reason: str = Field(default="", description="为什么这样选择")


class ResearchPlan(BaseModel):
    brief: str = Field(description="一句话研究目标")
    sub_questions: list[str] = Field(
        default_factory=list,
        description="需要回答的 2-4 个子问题",
    )
class ReviewResult(BaseModel):
    passed: bool = Field(description="研究是否已经覆盖简报和所有子问题")
    feedback: str = Field(description="审核意见")
    uncovered_questions: list[str] = Field(
        default_factory=list,
        description="还没有答好的子问题",
    )
    next_query: str = Field(
        default="",
        description="如果没通过，建议补充搜索的关键词",
    )
    
