#!/usr/bin/env python3
"""
PDF Processor for Aadhaar Bot
Cracks password and extracts images using pikepdf & PyMuPDF
"""

import os
import sys
import re
import shutil          # ✅ FIX: missing import যোগ করা হয়েছে
import io
import pikepdf
import fitz  # PyMuPDF


def extract_images_from_pdf(pdf_path, output_dir):
    """Extract all images from PDF and save them."""
    doc = fitz.open(pdf_path)
    image_paths = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            img_filename = f"page_{page_num+1}_img_{img_index+1}.{image_ext}"
            img_path = os.path.join(output_dir, img_filename)
            with open(img_path, "wb") as f:
                f.write(image_bytes)
            image_paths.append(img_path)
    doc.close()
    return image_paths


def crack_password(pdf_path, name):
    """
    Try to crack password using name patterns.
    Aadhaar PDF password format: First 4 letters of name (CAPS) + Birth Year (YYYY)
    Example: RAJESH KUMAR born 1990 → RAJE1990
    """
    name_clean = re.sub(r'[^a-zA-Z]', '', name)
    if len(name_clean) < 4:
        name_clean = (name_clean + "XXXX")[:4]
    first4 = name_clean[:4].upper()

    # Try common year patterns
    possible_passwords = set()
    for year in range(1950, 2026):   # ✅ FIX: 2010 -> 2025 পর্যন্ত বাড়ানো
        possible_passwords.add(f"{first4}{year}")

    # Common fallback patterns
    possible_passwords.add(first4)
    possible_passwords.add(first4.lower())
    possible_passwords.add(first4.capitalize())
    for suffix in ['', '!', '@', '#', '123']:
        possible_passwords.add(f"{first4}{suffix}")

    for pwd in possible_passwords:
        try:
            with pikepdf.open(pdf_path, password=pwd) as pdf:
                return pwd
        except pikepdf.PasswordError:      # ✅ FIX: সঠিক exception
            continue
        except Exception:
            continue
    return None


def main():
    if len(sys.argv) < 5:
        print("ERROR|Insufficient arguments")
        return

    pdf_path = sys.argv[1]
    name = sys.argv[2]
    output_dir = sys.argv[3]
    chat_id = sys.argv[4]

    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(pdf_path):
        print(f"ERROR|PDF file not found: {pdf_path}")
        return

    password = crack_password(pdf_path, name)

    if password:
        try:
            pdf = pikepdf.open(pdf_path, password=password)
            unlocked_pdf = os.path.join(output_dir, f"Aadhaar_{chat_id}_unlocked.pdf")
            pdf.save(unlocked_pdf)
            pdf.close()

            img_dir = os.path.join(output_dir, f"img_{chat_id}")
            os.makedirs(img_dir, exist_ok=True)
            image_paths = extract_images_from_pdf(pdf_path, img_dir)

            front_img = image_paths[0] if len(image_paths) > 0 else ""
            back_img = image_paths[1] if len(image_paths) > 1 else ""

            # Extract 12-digit UID from PDF
            uid = "Unknown"
            try:
                doc = fitz.open(unlocked_pdf)
                text = ""
                for page in doc:
                    text += page.get_text()
                doc.close()
                matches = re.findall(r'\b\d{4}\s?\d{4}\s?\d{4}\b', text)
                if matches:
                    uid = re.sub(r'\s', '', matches[0])
                else:
                    match = re.search(r'\b\d{12}\b', text)
                    if match:
                        uid = match.group(0)
            except Exception:
                pass

            print(f"SUCCESS|{uid}|{unlocked_pdf}|{front_img}|{back_img}|{password}")
            return

        except Exception as e:
            print(f"ERROR|Failed to process PDF: {e}")
            return
    else:
        locked_copy = os.path.join(output_dir, f"Aadhaar_{chat_id}_locked.pdf")
        try:
            shutil.copy2(pdf_path, locked_copy)     # ✅ FIX: shutil import করায় কাজ করবে
            print(f"UNCRACKED|{locked_copy}")
        except Exception as e:
            print(f"ERROR|Could not copy locked PDF: {e}")
        return


if __name__ == "__main__":
    main()