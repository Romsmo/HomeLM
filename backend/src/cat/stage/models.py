from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

MAX_CHART_POINTS = 500


class ChartDataset(BaseModel):
    label: str = Field(max_length=100)
    data: list[float] = Field(max_length=MAX_CHART_POINTS)


class ChartSpec(BaseModel):
    """Strukturierte Diagrammdaten; der Browser zeichnet sie mit Chart.js."""

    type: Literal["bar", "line", "pie", "doughnut"]
    labels: list[str] = Field(min_length=1, max_length=MAX_CHART_POINTS)
    datasets: list[ChartDataset] = Field(min_length=1, max_length=8)
    x_label: str | None = Field(default=None, max_length=100)
    y_label: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _same_length(self) -> Self:
        for ds in self.datasets:
            if len(ds.data) != len(self.labels):
                raise ValueError(
                    f"Datensatz '{ds.label}' hat {len(ds.data)} Werte, erwartet {len(self.labels)}"
                )
        return self


class StageItem(BaseModel):
    id: str
    kind: Literal["html", "chart", "markdown", "devices"]
    title: str
    # html: Dokument-Fragment; markdown: Text; devices: optionaler Raumfilter. Bei chart leer.
    content: str = ""
    chart: ChartSpec | None = None
    created_at: float
