from packages.ingestion.parser import parse_legal_text


def test_parser_preserves_article_clause_point():
    result = parse_legal_text(
        """CHƯƠNG I QUY ĐỊNH\nĐiều 5. Thử việc\n1. Nội dung khoản một.\na) Nội dung điểm a.\n2. Nội dung khoản hai."""
    )
    assert [(x.article, x.clause, x.point) for x in result] == [
        ("5", "1", None),
        ("5", "1", "a"),
        ("5", "2", None),
    ]
    assert result[1].chapter == "CHƯƠNG I QUY ĐỊNH"
