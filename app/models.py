"""Pydantic models for goals / tasks / assistant / chat."""

from __future__ import annotations

import math
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class GoalItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[0-9a-f]{32}$")
    project: Literal["ipis"]
    goal: str = Field(min_length=1, max_length=200)
    target: float = 0
    current: float = 0
    unit: str = Field(default="", max_length=20)
    kind: Literal["numeric", "checklist"] = "numeric"
    memo: str = Field(default="", max_length=500)

    @field_validator("goal", "memo")
    @classmethod
    def trimmed_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def check_numeric_goal(self) -> "GoalItem":
        if self.kind == "numeric" and (not math.isfinite(self.target) or self.target <= 0):
            raise ValueError("수치형 목표는 0보다 큰 목표 수치가 필요합니다.")
        if not math.isfinite(self.current) or self.current < 0:
            raise ValueError("완료 수치는 0 이상의 유한한 수여야 합니다.")
        if not self.goal:
            raise ValueError("목표 내용은 공백만으로 저장할 수 없습니다.")
        return self


class WeekGoals(BaseModel):
    start: str = ""
    items: list[GoalItem] = []


class DayGoals(BaseModel):
    date: str = ""
    items: list[GoalItem] = []


class Goals(BaseModel):
    week: WeekGoals = WeekGoals()
    day: DayGoals = DayGoals()


class GoalProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: float | None = None
    project: Literal["ipis"] | None = None
    goal: str | None = Field(default=None, max_length=200)
    target: float | None = None
    unit: str | None = Field(default=None, max_length=20)
    kind: Literal["numeric", "checklist"] | None = None
    memo: str | None = Field(default=None, max_length=500)
    expected: GoalItem
    expected_date: str

    @model_validator(mode="after")
    def check_has_edit(self) -> "GoalProgressUpdate":
        if all(
            value is None
            for value in (self.current, self.project, self.goal, self.target, self.unit, self.kind, self.memo)
        ):
            raise ValueError("변경할 내용이 없습니다.")
        if self.goal is not None and not self.goal.strip():
            raise ValueError("목표 내용은 공백만으로 저장할 수 없습니다.")
        return self


class TaskItem(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    date: str
    title: str
    done: StrictBool
    goal_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    priority: Literal["high", "mid", "low"] = "mid"
    memo: str = Field(default="", max_length=500)

    @field_validator("date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        from datetime import datetime

        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from error
        if parsed.strftime("%Y-%m-%d") != value:
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
        return value

    @field_validator("title")
    @classmethod
    def trimmed_title(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 200:
            raise ValueError("할 일은 공백 제외 1~200자여야 합니다.")
        return value

    @field_validator("memo")
    @classmethod
    def trimmed_memo(cls, value: str) -> str:
        return value.strip()


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    date: str
    goal_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    priority: Literal["high", "mid", "low"] = "mid"
    memo: str = Field(default="", max_length=500)

    @field_validator("date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        return TaskItem.valid_date(value)

    @field_validator("title", "memo")
    @classmethod
    def trimmed_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def check_title(self) -> "TaskCreate":
        if not self.title or len(self.title) > 200:
            raise ValueError("할 일은 공백 제외 1~200자여야 합니다.")
        return self


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: StrictBool | None = None
    title: str | None = Field(default=None, max_length=200)
    priority: Literal["high", "mid", "low"] | None = None
    memo: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_has_edit(self) -> "TaskUpdate":
        if self.done is None and self.title is None and self.priority is None and self.memo is None:
            raise ValueError("변경할 내용이 없습니다.")
        if self.title is not None and (not self.title.strip() or len(self.title.strip()) > 200):
            raise ValueError("할 일은 공백 제외 1~200자여야 합니다.")
        return self


class TaskLinkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class AssistantPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proactive_enabled: StrictBool = True
    morning: str = "09:00"
    midday: str = "12:00"
    wrap_up: str = "18:00"
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"

    @field_validator("morning", "midday", "wrap_up", "quiet_start", "quiet_end")
    @classmethod
    def valid_clock(cls, value: str) -> str:
        from app.storage import _valid_clock

        return _valid_clock(value)


class AssistantPreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proactive_enabled: StrictBool | None = None
    morning: str | None = None
    midday: str | None = None
    wrap_up: str | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None

    @field_validator("morning", "midday", "wrap_up", "quiet_start", "quiet_end")
    @classmethod
    def valid_clock(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from app.storage import _valid_clock

        return _valid_clock(value)


class AssistantTaskSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    title: str = Field(min_length=1, max_length=200)
    date: str
    done: StrictBool

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        return TaskItem.trimmed_title(value)

    @field_validator("date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        return TaskItem.valid_date(value)

    @model_validator(mode="after")
    def must_be_unfinished(self) -> "AssistantTaskSnapshot":
        if self.done:
            raise ValueError("expected task snapshot must be unfinished")
        return self


class AssistantAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["create_task", "complete_task", "reschedule_task"]
    title: str | None = Field(default=None, max_length=200)
    date: str | None = None
    task_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    expected: AssistantTaskSnapshot | None = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("할 일 제목은 비워 둘 수 없습니다.")
        return value

    @field_validator("date")
    @classmethod
    def valid_action_date(cls, value: str | None) -> str | None:
        return None if value is None else TaskItem.valid_date(value)

    @model_validator(mode="after")
    def validate_shape(self) -> "AssistantAction":
        if self.action == "create_task":
            if self.title is None or self.date is None or self.task_id is not None or self.expected is not None:
                raise ValueError("create_task에는 title과 date만 필요합니다.")
        elif self.action == "complete_task":
            if self.task_id is None or self.title is not None or self.date is not None or self.expected is None:
                raise ValueError("complete_task에는 task_id와 expected가 필요합니다.")
        elif self.task_id is None or self.date is None or self.title is not None or self.expected is None:
            raise ValueError("reschedule_task에는 task_id, date와 expected가 필요합니다.")
        if self.expected is not None and self.task_id != self.expected.id:
            raise ValueError("task_id와 expected.id가 일치해야 합니다.")
        return self


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
