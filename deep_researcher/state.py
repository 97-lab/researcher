from dataclasses import dataclass
import operator
from dataclasses import dataclass, field
from typing_extensions import Annotated


@dataclass
class State:
    research_topic:str
    search_query: str = ""
    search_results: str = ""
    summary: str = ""
    research_loop_count: int = 0   #记录已经研究了几轮，循环靠它来判断什么时候停
    sources_gathered: Annotated[list,operator.add]=field(default_factory=list)  #收集所有来源，最后写进报告
    search_query_history: Annotated[list,operator.add]=field(default_factory=list)