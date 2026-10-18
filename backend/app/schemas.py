from pydantic import BaseModel


class Link(BaseModel):
    text: str
    url: str


class Chunk(BaseModel):
    id: int
    heading: str
    text: str
    source: str
    title: str
    wordCount: int
    charCount: int


class PageDocument(BaseModel):

    page_id: str

    title: str
    url: str
    hostname: str   
    description: str

    headings: list[str]
    paragraphs: list[str]
    links: list[Link]

    chunks: list[Chunk]

    content: str
    wordCount: int