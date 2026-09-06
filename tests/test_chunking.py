from app.services.chunking_service import (
    TextChunk,
    chunk_text_stream,
    stream_file_lines,
)


def test_chunk_text_stream():
    lines = [
        ("This is the first line.\n", 0, 24),
        ("This is the second line.\n", 24, 49),
        ("This is the third line.\n", 49, 73),
    ]

    chunks = list(chunk_text_stream(iter(lines)))

    assert len(chunks) == 1

    chunk = chunks[0]

    assert isinstance(chunk, TextChunk)
    assert "first line" in chunk.text
    assert "second line" in chunk.text
    assert "third line" in chunk.text

    assert chunk.start_byte == 0
    assert chunk.end_byte == 73


def test_chunk_byte_offsets_support_utf8():
    text = "Hello 世界\n"

    encoded = text.encode("utf-8")

    lines = [
        (text, 0, len(encoded)),
    ]

    chunks = list(chunk_text_stream(iter(lines)))

    assert len(chunks) == 1

    chunk = chunks[0]

    assert chunk.text == text
    assert chunk.start_byte == 0
    assert chunk.end_byte == len(encoded)


def test_stream_file_lines(tmp_path):
    file_path = tmp_path / "sample.txt"

    content = (
        "First line.\r\n"
        "Second line 世界.\r\n"
        "Third line.\r\n"
    )

    file_path.write_bytes(content.encode("utf-8"))

    lines = list(
        stream_file_lines(str(file_path))
    )

    assert len(lines) == 3

    first_text, first_start, first_end = lines[0]

    expected_first = "First line.\r\n"

    assert first_text == expected_first
    assert first_start == 0
    assert first_end == len(
        expected_first.encode("utf-8")
    )

    second_text, second_start, second_end = lines[1]

    expected_second = "Second line 世界.\r\n"

    assert second_text == expected_second
    assert second_start == first_end
    assert second_end == (
        second_start
        + len(expected_second.encode("utf-8"))
    )

    third_text, third_start, third_end = lines[2]

    expected_third = "Third line.\r\n"

    assert third_text == expected_third
    assert third_start == second_end
    assert third_end == (
        third_start
        + len(expected_third.encode("utf-8"))
    )


def test_stream_file_lines_byte_offsets_match_file_size(tmp_path):
    file_path = tmp_path / "unicode.txt"

    content = (
        "Hello 世界\r\n"
        "日本語のテストです。\r\n"
        "Final line.\r\n"
    )

    raw_content = content.encode("utf-8")

    file_path.write_bytes(raw_content)

    lines = list(
        stream_file_lines(str(file_path))
    )

    assert len(lines) == 3

    assert lines[-1][2] == len(raw_content)

    assert lines[0][1] == 0

    for previous, current in zip(lines, lines[1:]):
        assert previous[2] == current[1]

    reconstructed = "".join(
        text for text, _, _ in lines
    )

    assert reconstructed == content


def test_chunk_overlap():
    # Force multiple chunks.
    first_text = "A" * 3000
    second_text = "B" * 3000

    lines = [
        (
            first_text,
            0,
            len(first_text.encode("utf-8")),
        ),
        (
            second_text,
            len(first_text.encode("utf-8")),
            len(
                (
                    first_text + second_text
                ).encode("utf-8")
            ),
        ),
    ]

    chunks = list(
        chunk_text_stream(iter(lines))
    )

    assert len(chunks) == 2

    first_chunk = chunks[0]
    second_chunk = chunks[1]

    # First chunk should contain the first line.
    assert first_chunk.text.startswith("A")

    # Second chunk should contain:
    # - 500 characters of overlap from chunk 1
    # - followed by the second line.
    assert second_chunk.text.startswith(
        "A" * 500
    )

    assert second_chunk.text.endswith(
        "B" * 3000
    )

    # Verify exact overlap.
    assert second_chunk.text[:500] == (
        first_chunk.text[-500:]
    )


def test_chunk_byte_offsets():
    first_text = "A" * 3000
    second_text = "B" * 3000

    first_start = 0
    first_end = len(
        first_text.encode("utf-8")
    )

    second_start = first_end
    second_end = second_start + len(
        second_text.encode("utf-8")
    )

    lines = [
        (
            first_text,
            first_start,
            first_end,
        ),
        (
            second_text,
            second_start,
            second_end,
        ),
    ]

    chunks = list(
        chunk_text_stream(iter(lines))
    )

    assert len(chunks) == 2

    first_chunk = chunks[0]
    second_chunk = chunks[1]

    # First chunk maps to the first source region.
    assert first_chunk.start_byte == 0
    assert first_chunk.end_byte == first_end

    # Second chunk starts at the second source line.
    # The 500-character overlap is contextual text
    # from the previous chunk and does not change the
    # source byte start.
    assert second_chunk.start_byte == second_start
    assert second_chunk.end_byte == second_end