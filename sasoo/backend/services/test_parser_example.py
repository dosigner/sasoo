"""
Example usage of PDF Parser and Section Splitter.

This demonstrates the complete workflow:
1. Parse PDF to extract text, figures, tables, metadata
2. Split text into logical sections
3. Get phase-specific inputs for the 4-phase analysis
"""
import asyncio
from pathlib import Path
from pdf_parser import PdfParser
from section_splitter import SectionSplitter


async def main():
    """Example workflow."""

    # Initialize services
    parser = PdfParser(output_base_dir=Path("./test_papers"))
    splitter = SectionSplitter()

    # Example PDF path (replace with actual path)
    pdf_path = "./sample_paper.pdf"

    print(f"Parsing PDF: {pdf_path}")
    print("-" * 80)

    try:
        # Step 1: Parse PDF
        parsed_paper = await parser.parse(pdf_path)

        print(f"\n✓ PDF parsed successfully!")
        print(f"\nMetadata:")
        print(f"  Title: {parsed_paper.metadata.title}")
        print(f"  Authors: {', '.join(parsed_paper.metadata.authors[:3])}")
        if len(parsed_paper.metadata.authors) > 3:
            print(f"           + {len(parsed_paper.metadata.authors) - 3} more")
        print(f"  Year: {parsed_paper.metadata.year}")
        print(f"  DOI: {parsed_paper.metadata.doi}")
        print(f"  Pages: {parsed_paper.metadata.page_count}")
        print(f"  File size: {parsed_paper.metadata.file_size_bytes / 1024 / 1024:.2f} MB")

        print(f"\nExtracted content:")
        print(f"  Text length: {len(parsed_paper.full_text):,} characters")
        print(f"  Figures: {len(parsed_paper.figures)}")
        print(f"  Tables: {len(parsed_paper.tables)}")

        print(f"\nOutput directory: {parsed_paper.base_path}")
        print(f"Figures saved to: {parsed_paper.figures_dir}")

        # Show figure details
        if parsed_paper.figures:
            print(f"\nFigure details:")
            for fig in parsed_paper.figures[:3]:  # Show first 3
                print(f"  {fig.figure_id} (page {fig.page_number})")
                print(f"    Image: {fig.image_path.name}")
                if fig.caption:
                    caption_preview = fig.caption[:100] + "..." if len(fig.caption) > 100 else fig.caption
                    print(f"    Caption: {caption_preview}")

        # Show table details
        if parsed_paper.tables:
            print(f"\nTable details:")
            for tbl in parsed_paper.tables[:2]:  # Show first 2
                print(f"  {tbl.table_id} (page {tbl.page_number})")
                print(f"    Dimensions: {len(tbl.data)} rows × {len(tbl.data[0]) if tbl.data else 0} cols")
                if tbl.caption:
                    caption_preview = tbl.caption[:100] + "..." if len(tbl.caption) > 100 else tbl.caption
                    print(f"    Caption: {caption_preview}")

        # Step 2: Split into sections
        print(f"\n{'=' * 80}")
        print("Splitting into sections...")
        print("-" * 80)

        sections = splitter.split(parsed_paper.full_text)

        print(f"\n✓ Detected {len(sections)} sections:")
        for section_name, text in sections.items():
            word_count = len(text.split())
            print(f"  {section_name}: {word_count:,} words")

        # Step 3: Get phase-specific inputs
        print(f"\n{'=' * 80}")
        print("Preparing phase-specific inputs...")
        print("-" * 80)

        # Phase 1: Screening
        screening_input = splitter.get_screening_input(sections)
        print(f"\nPhase 1 (Screening) input:")
        print(f"  Length: {len(screening_input.split()):,} words")
        print(f"  Preview: {screening_input[:200]}...")

        # Phase 2: Visual Analysis
        visual_sections = splitter.get_visual_input(sections)
        print(f"\nPhase 2 (Visual Analysis) sections:")
        print(f"  Sections to analyze: {', '.join(visual_sections)}")
        print(f"  Figures available: {len(parsed_paper.figures)}")
        print(f"  Tables available: {len(parsed_paper.tables)}")

        # Phase 3: Recipe Extraction
        recipe_input = splitter.get_recipe_input(sections)
        print(f"\nPhase 3 (Recipe) input:")
        print(f"  Length: {len(recipe_input.split()):,} words")
        print(f"  Preview: {recipe_input[:200]}...")

        # Phase 4: Deep Dive
        deepdive_input = splitter.get_deepdive_input(sections)
        print(f"\nPhase 4 (Deep Dive) input:")
        print(f"  Length: {len(deepdive_input.split()):,} words")
        print(f"  Preview: {deepdive_input[:200]}...")

        # Token savings estimation
        print(f"\n{'=' * 80}")
        print("Token savings analysis...")
        print("-" * 80)

        savings = splitter.estimate_token_savings(sections)
        print(f"\nEstimated token savings vs. full text:")
        for phase, pct in savings.items():
            print(f"  {phase.capitalize()}: {pct:.1f}% reduction")

        # Section statistics
        stats = splitter.get_section_statistics(sections)
        total_words = sum(stats.values())
        print(f"\nTotal word count: {total_words:,}")
        print(f"Average tokens per phase:")
        print(f"  Screening: ~{len(screening_input.split()) * 1.3:.0f} tokens")
        print(f"  Recipe: ~{len(recipe_input.split()) * 1.3:.0f} tokens")
        print(f"  Deep Dive: ~{len(deepdive_input.split()) * 1.3:.0f} tokens")
        print(f"  Full text: ~{total_words * 1.3:.0f} tokens")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        raise

    finally:
        await parser.close()


if __name__ == "__main__":
    asyncio.run(main())
