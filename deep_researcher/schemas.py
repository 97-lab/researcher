from  pydantic import BaseModel,Field

class Query(BaseModel):
    query: str =Field(description='实际的搜索词')
    rationale: str = Field(description="为什么这个搜索词相关")


class FollowUpQuery(BaseModel):
    follow_up_query: str = Field(description="追问搜索词")
    knowledge_gap: str = Field(description="总结中缺失的信息")


class UserIntent(BaseModel):
    action: str = Field(description="动作：new_research / view / follow_up / exit / unknown")
    researcher_id: str = Field(default="", description="分支编号，如 r1")
    topic: str = Field(default="", description="研究主题")
    query_index: int = Field(default=0, description="追问第几个搜索词，从 1 开始")
    follow_up: str = Field(default="", description="追问内容")


    