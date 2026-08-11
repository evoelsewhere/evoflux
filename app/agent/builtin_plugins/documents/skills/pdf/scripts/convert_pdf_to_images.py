from pathlib import Path
import sys

import pypdfium2 as pdfium


def convert(pdf_path: str, output_dir: str, max_dim: int = 1000) -> None:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(pdf_path)
    page_count = len(document)
    try:
        for index in range(page_count):
            page = document[index]
            try:
                width, height = page.get_size()
                scale = min(200 / 72, max_dim / max(width, height))
                bitmap = page.render(scale=max(scale, 0.1))
                try:
                    image = bitmap.to_pil()
                    image_path = destination / f"page_{index + 1}.png"
                    image.save(image_path)
                    print(
                        f"Saved page {index + 1} as {image_path} (size: {image.size})"
                    )
                finally:
                    bitmap.close()
            finally:
                page.close()
    finally:
        document.close()

    print(f"Converted {page_count} pages to PNG images")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: convert_pdf_to_images.py [input pdf] [output directory]")
        sys.exit(1)
    pdf_path = sys.argv[1]
    output_directory = sys.argv[2]
    convert(pdf_path, output_directory)
