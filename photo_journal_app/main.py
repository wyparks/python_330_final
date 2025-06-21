from datetime import datetime
import os
import time
from typing import Annotated

import aiofiles
from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2_fragments.fastapi import Jinja2Blocks
from PIL import Image
from tinydb import TinyDB, Query



app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Blocks(directory="templates")

def get_db():
    return TinyDB("db.json")

PHOTOS_PER_PAGE = 3

# Utility functions

def get_sorted_photos(all_photos, current_photo_count, new_photo_count):
    return sorted(all_photos,
                  key=lambda d: datetime.strptime(d["uploaded_at"], "%m/%d/%Y %I:%M:%S%p"),
                  reverse=True)[current_photo_count:new_photo_count]

def resize_image_for_web(photo_file_path):
    image_file = Image.open(f"static/{photo_file_path}")
    if image_file.width > image_file.height and image_file.width > 1920:
        image_file.thumbnail((1920, 1080))
    if image_file.width < image_file.height and image_file.width > 900:
        image_file.thumbnail((900, 1200))
    image_file.save(f"static{photo_file_path}")

# FastAPI routes

@app.get("/", response_class=HTMLResponse)
def photo_journal(request: Request, db: TinyDB = Depends(get_db)):
    sorted_photos = get_sorted_photos(db.all(), 0, PHOTOS_PER_PAGE)
    context = {
        "request": request,
        "photos": sorted_photos,
        "photo_count": PHOTOS_PER_PAGE,
    }
    return templates.TemplateResponse(request, name="photo_journal.html.jinja2", context=context)

@app.post("/post-photo", response_class=HTMLResponse)
async def post_photo(request: Request, entry: Annotated[str, Form()], photo_upload: UploadFile,
                     db: TinyDB = Depends(get_db)):
    valid_image_file = True
    photo_file_path = f"/images/{photo_upload.filename}"
    async with aiofiles.open(f"static{photo_file_path}", "wb") as out_file:
        content = await photo_upload.read()
        await out_file.write(content)
    try:
        with Image.open(f"static{photo_file_path}") as image_file:
            image_file.verify()
    except (IOError, SyntaxError):
        valid_image_file = False
        os.remove(f"static{photo_file_path}")
    if valid_image_file:
        resize_image_for_web(photo_file_path)
        uploaded_at = time.strftime("%m/%d/%Y %I:%M:%S%p")
        db.insert({"entry": entry,
                   "file_path": photo_file_path,
                   "uploaded_at": uploaded_at})
    sorted_photos = get_sorted_photos(db.all(), 0, PHOTOS_PER_PAGE)
    context = {
        "request": request,
        "photos": sorted_photos,
        "photo_count": PHOTOS_PER_PAGE,
        "invalid_image_file": not valid_image_file,
    }
    return templates.TemplateResponse(request, name="photo_journal.html.jinja2", context=context, block_name="photos")


@app.get("/edit-photo", response_class=HTMLResponse)
def get_edit_photo_form(request: Request, photo_id: int, db: TinyDB = Depends(get_db)):
    photo = db.get(doc_id=photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    photo["doc_id"] = photo_id
    context = {
        "request": request,
        "photo": photo
    }
    return templates.TemplateResponse(request, "edit_photo_form.html.jinja2", context=context)


@app.post("/edit-photo", response_class=HTMLResponse)
def edit_photo(
        request: Request,
        photo_id: Annotated[int, Form()],
        entry: Annotated[str, Form()],
        db: TinyDB = Depends(get_db)
    ):
    photo = db.get(doc_id=photo_id)
    if photo is None:
        return HTMLResponse("Photo not found", status_code=404)

    db.update({"entry": entry}, doc_ids=[photo_id])

    # Update the photo dictionary for use in the returned context
    photo["entry"] = entry
    photo["doc_id"] = photo_id

    context = {"photo": photo, "request": request}


    return templates.TemplateResponse(
        request, "photo_journal.html.jinja2", context=context, block_name="click_to_edit_entry"
    )


@app.delete("/delete-photo", response_class=Response)
def delete_photo(photo_id: int, db: TinyDB = Depends(get_db)):
    # Get the photo record from the database
    photo = db.get(doc_id=photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Construct the path to the stored file
    file_path = f"static{photo['file_path']}"
    if os.path.exists(file_path):
        os.remove(file_path)

    # Remove the record from the database
    db.remove(doc_ids=[photo_id])

    return Response(status_code=200)


@app.get("/load-photos", response_class=HTMLResponse)
def load_photos(request: Request, photo_count: int, db: TinyDB = Depends(get_db)):
    # Compute the new total by adding the constant number of photos per page.
    new_photo_count = photo_count + PHOTOS_PER_PAGE
    sorted_photos = get_sorted_photos(db.all(), photo_count, new_photo_count)

    context = {
        "request": request,
        "photos": sorted_photos,
        "photo_count": new_photo_count,
    }

    # Return only the HTML fragment corresponding to the photos block.
    # This fragment will be appended to the already-loaded photos.
    return templates.TemplateResponse(request, "photo_journal.html.jinja2", context, block_name="photos")
