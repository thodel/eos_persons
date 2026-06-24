import fitz  # PyMuPDF
import re
import json
import os
import glob

def extract_articles_from_pdf(pdf_path):
    """
    Extracts lexicon articles from a single PDF.
    Returns a list of dictionaries containing the article data.
    """
    # Open the document
    doc = fitz.open(pdf_path)

    articles = []
    current_article = {"keyword": None, "content": "", "page": 0, "backlink": ""}

    # Heuristic: A keyword is typically 2 or more uppercase letters (including German umlauts)
    # at the very beginning of a line.
    keyword_pattern = re.compile(r'^([A-ZÄÖÜ]{2,}(?:\s[A-ZÄÖÜ]{2,})?)[,\.]?\s*(.*)')

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)

        # Extract plain text from the page
        text = page.get_text("text")
        lines = text.split('\n')

        # 1-based index for standard PDF viewer links
        actual_page_number = page_num + 1

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if the line indicates a new lexicon entry
            match = keyword_pattern.match(line)

            # Additional check: ensure it's not a run-on sentence in all caps
            if match and len(match.group(1)) > 2:
                # Save the completed previous article
                if current_article["keyword"]:
                    # Clean up the trailing spaces
                    current_article["content"] = current_article["content"].strip()
                    articles.append(current_article)

                # Start a new article
                keyword = match.group(1).strip()
                remainder_of_line = match.group(2).strip()

                # Create absolute path for the backlink
                abs_path = os.path.abspath(pdf_path)
                backlink = f"file://{abs_path}#page={actual_page_number}"

                current_article = {
                    "keyword": keyword,
                    "content": remainder_of_line + " ",
                    "page": actual_page_number,
                    "backlink": backlink,
                    "source_file": os.path.basename(pdf_path)
                }
            else:
                # If it's not a new keyword, append text to the current article
                if current_article["keyword"]:
                    current_article["content"] += line + " "

    # Don't forget to append the very last article in the document
    if current_article["keyword"]:
        current_article["content"] = current_article["content"].strip()
        articles.append(current_article)

    return articles

def process_directory(directory_path, output_json="extracted_lexicon.json"):
    """
    Processes all PDFs in a directory and compiles them into a single JSON dataset.
    """
    all_articles = []
    pdf_files = glob.glob(os.path.join(directory_path, "*.pdf"))

    print(f"Found {len(pdf_files)} PDF files. Starting extraction...")

    for pdf_file in pdf_files:
        print(f"Processing: {os.path.basename(pdf_file)}")
        articles = extract_articles_from_pdf(pdf_file)
        all_articles.extend(articles)
        print(f" -> Extracted {len(articles)} articles.")

    # Save everything to JSON
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=4)

    print(f"\nExtraction complete! Data saved to {output_json}")

if __name__ == "__main__":
    # Example usage:
    # Set this to the folder containing your PDF files
    TARGET_DIRECTORY = "./"
    process_directory(TARGET_DIRECTORY)
