from collections.abc import Iterator
from dataclasses import dataclass


TARGET_CHUNK_SIZE = 4000
OVERLAP_SIZE = 500


@dataclass
class TextChunk:
    text: str
    start_byte: int
    end_byte: int


def chunk_text_stream(
    lines: Iterator[tuple[str, int, int]],
) -> Iterator[TextChunk]:
    """
    Build text chunks from a stream of lines.

    Each input item contains:
        text
        start_byte
        end_byte

    The chunker keeps memory bounded by accumulating only the
    current chunk plus a small overlap from the previous chunk.
    """

    current_parts: list[str] = []
    current_start_byte: int | None = None
    current_end_byte: int | None = None
    current_size = 0

    for text, start_byte, end_byte in lines:
        text_size = len(text)

        if current_start_byte is None:
            current_start_byte = start_byte

        if (
            current_parts
            and current_size + text_size > TARGET_CHUNK_SIZE
        ):
            chunk_text = "".join(current_parts)

            yield TextChunk(
                text=chunk_text,
                start_byte=current_start_byte,
                end_byte=current_end_byte
                if current_end_byte is not None
                else start_byte,
            )

            overlap_text = chunk_text[-OVERLAP_SIZE:]

            current_parts = [overlap_text]
            current_size = len(overlap_text)

            # The overlap belongs to the previous chunk's source
            # location. The next incoming line extends the chunk.
            current_start_byte = start_byte

        current_parts.append(text)
        current_size += text_size
        current_end_byte = end_byte

    if current_parts:
        chunk_text = "".join(current_parts)

        yield TextChunk(
            text=chunk_text,
            start_byte=current_start_byte
            if current_start_byte is not None
            else 0,
            end_byte=current_end_byte
            if current_end_byte is not None
            else 0,
        )

def stream_file_lines(
    file_path: str,
) -> Iterator[tuple[str, int, int]]:
    """
    Read a UTF-8 text file line-by-line while tracking
    the original byte offsets.
    """

    byte_offset = 0

    with open(
        file_path,
        "rb",
        buffering=1024 * 1024,
    ) as input_file:
        while True:
            line_start = byte_offset

            raw_line = input_file.readline()

            if not raw_line:
                break

            line_end = line_start + len(raw_line)

            byte_offset = line_end

            text = raw_line.decode(
                "utf-8",
                errors="replace",
            )

            yield text, line_start, line_end