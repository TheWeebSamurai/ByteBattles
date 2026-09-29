import io
import json
import logging
import zipfile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from fastapi import APIRouter, Depends, status, HTTPException, UploadFile, Form, File, Query
from sqlalchemy.orm import Session
from typing import List, Dict, BinaryIO

from ..schemas.problems import ProblemResponse, ProblemListResponse, ProblemDetailResponse, ProblemArrayDataValidator, TagCreate, ProblemCreateResponse, ProblemUpdate, TestCaseSetResponse
from ..utils import oauth2
from ..database import get_db

from shared.core import get_storage_testcases, get_storage_submission_code
from shared.models import (
    Problem, Category, TestCase, # problems
    Submission, # submissions
    User, # users
    Difficulty # enums
)

router = APIRouter(
    prefix='/problems',
    tags=["Problems"]
)

logger = logging.getLogger(__name__)

def _validate_testcase_archive(filename: str | None, contents: bytes):
    if not filename or not filename.lower().endswith(".zip"):
        raise HTTPException(detail="Only ZIP files are allowed", status_code=status.HTTP_400_BAD_REQUEST)

    try:
        zip_file = zipfile.ZipFile(io.BytesIO(contents))
    except zipfile.BadZipFile:
        raise HTTPException(detail="Invalid ZIP file", status_code=status.HTTP_400_BAD_REQUEST)

    archive_name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    prefix = archive_name[:-4]
    all_files = zip_file.namelist()
    input_files = sorted(
        path for path in all_files
        if path.startswith(prefix + "/inputs/") and not path.endswith("/")
    )
    output_files = sorted(
        path for path in all_files
        if path.startswith(prefix + "/outputs/") and not path.endswith("/")
    )

    if not input_files or not output_files:
        zip_file.close()
        raise HTTPException(detail="ZIP must contain inputs/ and outputs/", status_code=status.HTTP_400_BAD_REQUEST)
    if len(input_files) != len(output_files):
        zip_file.close()
        raise HTTPException(detail="Mismatch between input and output files", status_code=status.HTTP_400_BAD_REQUEST)

    testcase_pairs = []
    for input_path, output_path in zip(input_files, output_files):
        input_name = input_path.rsplit("/", 1)[-1]
        output_name = output_path.rsplit("/", 1)[-1]
        if input_name != output_name:
            zip_file.close()
            raise HTTPException(
                detail="Mismatch in input and output file names",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        testcase_pairs.append((input_path, output_path))

    return zip_file, testcase_pairs

def _problem_detail(problem: Problem):
    return {
        "id": problem.id,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "tags": [tag.slug for tag in problem.tags],
        "accepted_submissions": problem.accepted_submissions,
        "description": problem.description,
        "constraints": problem.constraints,
        "input_desc": problem.input_desc,
        "output_desc": problem.output_desc,
        "sample_io": problem.sample_io,
        "explanation": problem.explanation,
        "memory_limit_mb": problem.memory_limit_mb,
        "time_limit_sec": problem.time_limit_sec,
        "source": problem.source,
        "editorial": problem.editorial,
        "visibility": problem.visibility,
    }

@router.post('/tag', status_code=status.HTTP_201_CREATED, response_model=TagCreate)
def create_tag(
    tag: TagCreate,
    current_user: User = Depends(oauth2.get_current_admin),
    db: Session = Depends(get_db),
):
    existing_tag = db.query(Category).filter(
        (Category.slug == tag.slug) | (Category.name == tag.name)
    ).first()
    if existing_tag:
        raise HTTPException(
            detail="A tag with this name or slug already exists",
            status_code=status.HTTP_409_CONFLICT,
        )

    category = Category(name=tag.name, slug=tag.slug)
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            detail="A tag with this slug already exists",
            status_code=status.HTTP_409_CONFLICT,
        )

    return {"name": category.name, "slug": category.slug}

@router.get('/', status_code=status.HTTP_200_OK, response_model=ProblemListResponse)
def get_problems(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=5, le=100),
    difficulty: Difficulty | None = None,
    tag: str | None = None,
    title: str | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(oauth2.get_optional_current_admin),
):
    query = db.query(Problem)
    if not current_user:
        query = query.filter(Problem.visibility == True)
    if difficulty:
        query = query.filter(Problem.difficulty == difficulty)
    if tag:
        query = query.filter(Problem.tags.any(Category.slug == tag))
    if title:
        query = query.filter(Problem.title.ilike(f"%{title}%"))

    total = query.count()
    offset = (page - 1) * limit
    problems = query.order_by(Problem.id.asc()).offset(offset).limit(limit).all()

    items = [
        {
            "id": problem.id,
            "title": problem.title,
            "difficulty": problem.difficulty,
            "tags": [tag.slug for tag in problem.tags],
            "accepted_submissions": problem.accepted_submissions
        }
        for problem in problems
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": offset + len(problems) < total,
    }

@router.get('/{problem_id}', status_code=status.HTTP_200_OK, response_model=ProblemDetailResponse)
def get_problem_by_id(problem_id: str, db: Session = Depends(get_db), current_user: User | None = Depends(oauth2.get_optional_current_admin)):
    if current_user:
        problem = db.query(Problem).filter(Problem.id == problem_id).first()
    else:
        problem = db.query(Problem).filter(Problem.id == problem_id, Problem.visibility == True).first()
    
    if not problem:
        raise HTTPException(detail="requested problem doesn't exist", status_code=status.HTTP_404_NOT_FOUND)
    
    return _problem_detail(problem)

@router.patch('/{problem_id}', status_code=status.HTTP_200_OK, response_model=ProblemDetailResponse)
def update_problem(
    problem_id: str,
    updates: ProblemUpdate,
    current_user: User = Depends(oauth2.get_current_admin),
    db: Session = Depends(get_db),
):
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not problem:
        raise HTTPException(detail="Problem with given ID not found", status_code=status.HTTP_404_NOT_FOUND)

    changes = updates.model_dump(exclude_unset=True)
    if "tags" in changes:
        tags = changes["tags"]
        categories = db.query(Category).filter(Category.slug.in_(tags)).all() if tags else []
        if len(categories) != len(tags):
            raise HTTPException(detail="One or more tags are invalid", status_code=status.HTTP_400_BAD_REQUEST)
        changes["tags"] = categories

    for field_name, value in changes.items():
        setattr(problem, field_name, value)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(detail="Unable to update problem", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    db.refresh(problem)
    return _problem_detail(problem)

@router.post('/', status_code=status.HTTP_201_CREATED, response_model=ProblemCreateResponse)
async def create_problem(
    id: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    difficulty: Difficulty = Form(...),
    constraints: str = Form(...),
    tags: str = Form(...),
    sample_io: str = Form(...),

    input_desc: str = Form(...),
    output_desc: str = Form(...),
    explanation: str | None = Form(None),

    memory_limit_mb: int = Form(...),
    time_limit_sec: int = Form(...),

    visibility: bool = Form(False),
    source: str | None = Form(None),
    editorial: str | None = Form(None),

    tests_zip: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(oauth2.get_current_admin)
):
    
    # Validating Problem Id
    problem = db.query(Problem).filter(Problem.id == id).first()
    if problem:
        raise HTTPException(detail="Problem with key already exists", status_code=status.HTTP_400_BAD_REQUEST)
    
    zip_bytes = await tests_zip.read()
    zip_file, testcase_pairs = _validate_testcase_archive(tests_zip.filename, zip_bytes)
    
    # Validating Array Data
    try:
        array_data = ProblemArrayDataValidator(
            tags=json.loads(tags),
            constraints=json.loads(constraints),
            sample_io=json.loads(sample_io)
        )
    except (json.JSONDecodeError, ValidationError):
        zip_file.close()
        raise HTTPException(detail="Invalid format for tags, constraints, or sample_io", status_code=status.HTTP_400_BAD_REQUEST)
    
    categories = db.query(Category).filter(Category.slug.in_(array_data.tags)).all()
    if len(categories) != len(array_data.tags):
        zip_file.close()
        raise HTTPException(detail="One or more tags are invalid", status_code=status.HTTP_400_BAD_REQUEST)

    # Create Problem
    problem = Problem(
        id=id,
        title=title,
        description=description,
        difficulty=difficulty,

        constraints=array_data.constraints,
        tags=categories,
        sample_io=array_data.sample_io,

        input_desc=input_desc,
        output_desc=output_desc,
        explanation=explanation,

        memory_limit_mb=memory_limit_mb,
        time_limit_sec=time_limit_sec,

        visibility=visibility,
        source=source,
        editorial=editorial
    )

    try:
        db.add(problem)
        db.flush()

        # Upload Testcases
        for input_path, output_path in testcase_pairs:
            input_data = zip_file.read(input_path)
            output_data = zip_file.read(output_path)

            input_key = get_storage_testcases().upload_bytes(
                problem_id=problem.id,
                filename=input_path.split("/")[-1],
                data=input_data
            )

            output_key = get_storage_testcases().upload_bytes(
                problem_id=problem.id,
                filename=output_path.split("/")[-1],
                data=output_data
            )

            testcase = TestCase(
                problem_id=problem.id,
                input_key=input_key,
                output_key=output_key
            )
            db.add(testcase)
        
        db.commit()
    except Exception:
        db.rollback()
        get_storage_testcases().delete_problem_folder(problem.id)
        raise HTTPException(detail="Unknown Error Occurred", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        zip_file.close()

    return {
        "id": problem.id,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "tags": [category.slug for category in problem.tags],
        "testcases": len(testcase_pairs)
    }

@router.put('/{problem_id}/testcases', status_code=status.HTTP_200_OK, response_model=TestCaseSetResponse)
async def replace_problem_testcases(
    problem_id: str,
    tests_zip: UploadFile = File(...),
    current_user: User = Depends(oauth2.get_current_admin),
    db: Session = Depends(get_db),
):
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not problem:
        raise HTTPException(detail="Problem with given ID not found", status_code=status.HTTP_404_NOT_FOUND)

    zip_file, testcase_pairs = _validate_testcase_archive(tests_zip.filename, await tests_zip.read())
    storage = get_storage_testcases()
    uploaded_keys = []
    old_keys = [key for case in problem.testcases for key in (case.input_key, case.output_key)]

    try:
        new_testcases = []
        for input_path, output_path in testcase_pairs:
            input_key = storage.upload_bytes(
                problem_id=problem.id,
                filename=input_path.rsplit("/", 1)[-1],
                data=zip_file.read(input_path),
            )
            uploaded_keys.append(input_key)

            output_key = storage.upload_bytes(
                problem_id=problem.id,
                filename=output_path.rsplit("/", 1)[-1],
                data=zip_file.read(output_path),
            )
            uploaded_keys.append(output_key)
            new_testcases.append(TestCase(
                problem_id=problem.id,
                input_key=input_key,
                output_key=output_key,
            ))

        for testcase in problem.testcases:
            db.delete(testcase)
        db.flush()
        db.add_all(new_testcases)
        db.commit()
    except Exception:
        db.rollback()
        for object_key in uploaded_keys:
            try:
                storage.delete_file(object_key)
            except Exception:
                logger.exception("Failed to clean up testcase object %s", object_key)
        raise HTTPException(
            detail="Unable to replace problem testcases",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        zip_file.close()

    for object_key in old_keys:
        try:
            storage.delete_file(object_key)
        except Exception:
            logger.exception("Failed to delete replaced testcase object %s", object_key)

    return {"problem_id": problem.id, "testcases": len(new_testcases)}

@router.delete('/', status_code=status.HTTP_204_NO_CONTENT)
def delete_problem(problem_id: str, current_user: User = Depends(oauth2.get_current_admin), db: Session = Depends(get_db)):
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not problem:
        raise HTTPException(detail="Problem with given ID not found", status_code=status.HTTP_404_NOT_FOUND)
    
    submissions = db.query(Submission).filter(Submission.problem_id == problem.id).all()
    for submission in submissions:
        get_storage_submission_code().delete_file(submission.code_object_key)
    
    get_storage_testcases().delete_problem_folder(problem.id)
    
    db.delete(problem)
    db.commit()