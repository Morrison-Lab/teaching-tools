# FERPA: this script downloads student submissions, which are education records.
# AI agents must never run it, read its output, or open the files it downloads.
# Only the instructor runs it, by hand. See AGENTS.md.

# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "canvasapi",
# ]
# ///
# -*- coding: utf-8 -*-
"""
This script uses the canvasapi library to connect to a Canvas instance,
retrieve submissions for specified assignments, and download three sample
submissions based on score quantiles: the highest score, the median score,
and the lowest score.

Config:

Fill in the configuration variables below:
- API_URL: The base URL of your Canvas instance (e.g., "https://yourschool.instructure.com").
- API_KEY: Your Canvas API access token.
- COURSE_ID: The numerical ID of the course you want to access.
- DOWNLOAD_DIR: The destination download directory
- ASSIGNMENT_NAMES: A list of assignment names to process.

Setup:

Either install the canvasapi module and run this with python as usual, or use uv:
0.  Install uv - see https://docs.astral.sh/uv/getting-started/installation/
1.  Run: 
      uv run studentwork.py
"""
import os
from canvasapi import Canvas
from canvasapi.requester import Requester
from canvasapi.file import File
from canvasapi.exceptions import CanvasException, ResourceDoesNotExist, Unauthorized

import pdb

# --- START CONFIGURATION ---

# Your Canvas instance URL
API_URL = "https://wwu.instructure.com"

# Your Canvas API Key (generate this from your user settings in Canvas)
API_KEY = "1337" # <--- Replace with your api key

# The ID of the course containing the assignments
COURSE_ID = 1766660 # <--- Replace with your Course ID

# The local directory where files will be saved
DOWNLOAD_DIR = "" # <--- Replace with the path you want files saved to

# A list of assignment names (not IDs) to process from the course
ASSIGNMENT_NAMES = [] # <--- Replace with a list of assignment names

# Percentiles to sample for submission examples
# Format: {folder_name: percentile_value}
# Percentile values should be between 0.0 and 1.0
SUBMISSION_PERCENTILES = {
    "Poor": 0.25,      # 25th percentile
    "Average": 0.50,   # 50th percentile (median)
    "Good": 0.95       # 95th percentile
}

# --- END CONFIGURATION ---


def sanitize_filename(name):
    """
    Removes characters from a string that are invalid for file names.
    """
    return "".join(c for c in name if c.isalnum() or c in (' ', '.', '_')).rstrip()


def download_submission_examples(canvas, course_id, assignment_names):
    """
    Main function to process assignments and download submission examples.

    Args:
        canvas (Canvas): An initialized Canvas API object.
        course_id (int): The ID of the target course.
        assignment_names (list): A list of assignment names to process.
    """
    print(f"Starting submission download process for Course ID: {course_id}")

    try:
        # Get the course object from Canvas
        course = canvas.get_course(course_id)
        print(f"Successfully connected to course: '{course.name}'")

        # Create the base download directory if it doesn't exist
        if not os.path.exists(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR)
            print(f"Created base download directory: '{DOWNLOAD_DIR}'")

    except Unauthorized:
        print(f"Error: Unauthorized. Please check your API_KEY for Course ID {course_id}.")
        return
    except ResourceDoesNotExist:
        print(f"Error: Course with ID {course_id} was not found. Please check your COURSE_ID.")
        return
    except Exception as e:
        print(f"An unexpected error occurred while accessing the course: {e}")
        return

    # Get all assignments for the course
    try:
        all_assignments = list(course.get_assignments())
        print(f"Found {len(all_assignments)} total assignments in the course:")
    except Exception as e:
        print(f"Error retrieving assignments: {e}")
        return

    # Filter assignments by name
    assignments_to_process = []
    for assignment_name in assignment_names:
        found = False
        for assignment in all_assignments:
            if assignment.name == assignment_name:
                assignments_to_process.append(assignment)
                found = True
                break
        if not found:
            print(f"Warning: Assignment '{assignment_name}' not found in course")

    if not assignments_to_process:
        print("Error: No matching assignments found. Please check your assignment names.")
        return

    print(f"Found {len(assignments_to_process)} assignments to process")

    # Requester for attachment files
    requester = Requester(API_URL, API_KEY)
    
    # Process each assignment found
    for assignment in assignments_to_process:
        print("\n" + "="*50)
        print(f"Processing Assignment: {assignment.name}")

        try:
            print(f"Found assignment: '{assignment.name}'")

            # Get all submissions for the assignment. We include the user object
            # to get student names for file naming.
            submissions = list(assignment.get_submissions(include=["user", "submission_comments"]))

            # Filter for graded submissions that have attachments and a valid score
            graded_submissions = []
            for sub in submissions:
                if (hasattr(sub, 'score') and sub.score is not None and
                        hasattr(sub, 'attachments') and sub.attachments):
                    graded_submissions.append(sub)

            if len(graded_submissions) < len(SUBMISSION_PERCENTILES):
                print(f"Warning: Found only {len(graded_submissions)} graded submissions with files. "
                      f"At least {len(SUBMISSION_PERCENTILES)} are required to select percentiles.")
                print(f"Skipping download for assignment '{assignment.name}'.")
                continue

            # Sort the submissions by score in ascending order
            graded_submissions.sort(key=lambda s: s.score)

            # Calculate percentile indices based on configuration
            n = len(graded_submissions)
            quantile_submissions = {}
            
            for label, percentile in SUBMISSION_PERCENTILES.items():
                percentile_idx = max(0, int(n * percentile) - 1)
                quantile_submissions[label] = graded_submissions[percentile_idx]

            print(f"Identified {len(quantile_submissions)} submission examples to download.")

            # Download the file for each selected submission
            for quantile_label, submission in quantile_submissions.items():
                try:
                    # Create the quantile-specific directory
                    quantile_dir = os.path.join(DOWNLOAD_DIR, quantile_label)
                    if not os.path.exists(quantile_dir):
                        os.makedirs(quantile_dir)

                    attachment = submission.attachments[0]  # Download the first attachment
                    
                    # Get the file extension
                    original_filename = attachment.filename
                    file_extension = os.path.splitext(original_filename)[1]
                    
                    # Calculate percentage score
                    max_points = assignment.points_possible if hasattr(assignment, 'points_possible') and assignment.points_possible else 100
                    percent_score = round((submission.score / max_points) * 100, 1) if submission.score and max_points else 0

                    # Create new filename: {assignment_name}_{percent_score}.{extension}
                    clean_assignment_name = sanitize_filename(assignment.name)
                    file_name = f"{clean_assignment_name}_{percent_score}{file_extension}"
                    file_path = os.path.join(quantile_dir, file_name)

                    print(f"  -> Downloading '{file_name}' to {quantile_label} folder...")
                    attachment.download(file_path)
                    print(f"     Success! Saved to '{file_path}'")

                    # Download comments for this submission
                    comment_file_name = f"{clean_assignment_name}_{percent_score}.txt"
                    comment_file_path = os.path.join(quantile_dir, comment_file_name)
                    
                    try:
                        # Check if submission comments are already included in the submission
                        if hasattr(submission, 'submission_comments') and submission.submission_comments:
                            with open(comment_file_path, 'w', encoding='utf-8') as comment_file:
                                comment_file.write(f"Assignment: {assignment.name}\n")
                                comment_file.write(f"Student Score: {submission.score}/{max_points} ({percent_score}%)\n")
                                comment_file.write(f"Submission ID: {submission.id}\n")
                                comment_file.write("="*50 + "\n\n")
                                
                                for i, comment in enumerate(submission.submission_comments, 1):
                                    attachment = comment['attachments'][0]  # Download the first attachment
                                    original_filename = attachment['filename']
                                    file_extension = os.path.splitext(original_filename)[1]
                                    comment_attachment_file = f"{clean_assignment_name}_{percent_score}_comment{i}{file_extension}"
                                    comment_attachment_path = os.path.join(quantile_dir, comment_attachment_file)
                                    print(f"  -> Downloading '{comment_attachment_file}' to {quantile_label} folder...")
                                    attachment = File(requester, attachment)
                                    attachment.download(comment_attachment_path)
                                    print(f"     Success! Saved to '{file_path}'")

                                    comment_file.write(f"Comment {i}:\n")
                                    comment_file.write(f"Author: {comment.get('author_name', 'Unknown')}\n")
                                    comment_file.write(f"Date: {comment.get('created_at', 'Unknown')}\n")
                                    comment_file.write(f"Comment: {comment.get('comment', 'No comment text')}\n")
                                    comment_file.write("-" * 30 + "\n\n")
                            
                            print(f"     Comments saved to '{comment_file_path}'")
                        else:
                            # Try to get submission comments through the assignment
                            try:
                                comments = assignment.get_submission(submission.id, include=['submission_comments'])
                                
                                if hasattr(comments, 'submission_comments') and comments.submission_comments:
                                    with open(comment_file_path, 'w', encoding='utf-8') as comment_file:
                                        comment_file.write(f"Assignment: {assignment.name}\n")
                                        comment_file.write(f"Student Score: {submission.score}/{max_points} ({percent_score}%)\n")
                                        comment_file.write(f"Submission ID: {submission.id}\n")
                                        comment_file.write("="*50 + "\n\n")
                                        
                                        for i, comment in enumerate(comments.submission_comments, 1):
                                            attachment = comment['attachments'][0]  # Download the first attachment
                                            original_filename = attachment['filename']
                                            file_extension = os.path.splitext(original_filename)[1]
                                            comment_attachment_file = f"{clean_assignment_name}_{percent_score}_comment{i}{file_extension}"
                                            comment_attachment_path = os.path.join(quantile_dir, comment_attachment_file)
                                            print(f"  -> Downloading '{comment_attachment_file}' to {quantile_label} folder...")
                                            attachment = File(requester, attachment)
                                            attachment.download(comment_attachment_path)
                                            print(f"     Success! Saved to '{file_path}'")
                                            
                                            comment_file.write(f"Comment {i}:\n")
                                            comment_file.write(f"Author: {comment.get('author_name', 'Unknown')}\n")
                                            comment_file.write(f"Date: {comment.get('created_at', 'Unknown')}\n")
                                            comment_file.write(f"Comment: {comment.get('comment', 'No comment text')}\n")
                                            comment_file.write("-" * 30 + "\n\n")
                                    
                                    print(f"     Comments saved to '{comment_file_path}'")
                                else:
                                    # Create empty comment file to maintain consistency
                                    with open(comment_file_path, 'w', encoding='utf-8') as comment_file:
                                        comment_file.write(f"Assignment: {assignment.name}\n")
                                        comment_file.write(f"Student Score: {submission.score}/{max_points} ({percent_score}%)\n")
                                        comment_file.write(f"Submission ID: {submission.id}\n")
                                        comment_file.write("="*50 + "\n\n")
                                        comment_file.write("No comments found for this submission.\n")
                                    print(f"     No comments found, empty comment file saved to '{comment_file_path}'")
                            except Exception as comment_error:
                                # Create empty comment file even if we can't retrieve comments
                                with open(comment_file_path, 'w', encoding='utf-8') as comment_file:
                                    comment_file.write(f"Assignment: {assignment.name}\n")
                                    comment_file.write(f"Student Score: {submission.score}/{max_points} ({percent_score}%)\n")
                                    comment_file.write(f"Submission ID: {submission.id}\n")
                                    comment_file.write("="*50 + "\n\n")
                                    comment_file.write("No comments found for this submission.\n")
                                print(f"     No comments found, empty comment file saved to '{comment_file_path}'")
                    
                    except Exception as comment_error:
                        # Create empty comment file even if we can't retrieve comments
                        with open(comment_file_path, 'w', encoding='utf-8') as comment_file:
                            comment_file.write(f"Assignment: {assignment.name}\n")
                            comment_file.write(f"Student Score: {submission.score}/{max_points} ({percent_score}%)\n")
                            comment_file.write(f"Submission ID: {submission.id}\n")
                            comment_file.write("="*50 + "\n\n")
                            comment_file.write(f"Error retrieving comments: {comment_error}\n")
                        print(f"     Warning: Could not retrieve comments for submission {submission.id}: {comment_error}")
                        print(f"     Created placeholder comment file at '{comment_file_path}'")

                except CanvasException as e:
                    print(f"     Error: Could not download file for submission ID {submission.id}. Reason: {e}")
                except IndexError:
                    print(f"     Error: Submission ID {submission.id} reported attachments but none were found.")
                except Exception as e:
                    print(f"     An unexpected error occurred during download: {e}")

        except ResourceDoesNotExist:
            print(f"Error: Assignment '{assignment.name}' not found in this course.")
        except CanvasException as e:
            print(f"An API error occurred while processing assignment '{assignment.name}': {e}")
        except Exception as e:
            print(f"An unexpected error occurred for assignment '{assignment.name}': {e}")

    print("\n" + "="*50)
    print("Script finished.")


def main():
    """
    Initializes the Canvas API object and runs the main download logic.
    """
    if API_KEY == "YOUR_API_KEY" or COURSE_ID == 0 or not ASSIGNMENT_NAMES:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! PLEASE CONFIGURE THE SCRIPT BEFORE RUNNING              !!!")
        print("!!! Set API_URL, API_KEY, COURSE_ID, and ASSIGNMENT_NAMES   !!!")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        return

    try:
        # Initialize a new Canvas object
        canvas = Canvas(API_URL, API_KEY)
        # Verify that the API key is valid
        canvas.get_current_user()
    except Unauthorized:
        print("Error: The provided API_KEY is invalid or has expired. Please check your credentials.")
        return
    except Exception as e:
        print(f"Error: Failed to connect to Canvas at {API_URL}. Please check the URL and your connection.")
        print(f"Details: {e}")
        return

    # Run the main process
    download_submission_examples(canvas, COURSE_ID, ASSIGNMENT_NAMES)


if __name__ == "__main__":
    main()

