# Agent rules for teaching-tools

These rules apply to every AI agent working in this repository.

## Student records (FERPA)

Anything that names or identifies a student is a FERPA education record.
No LLM account we use is approved for that data.

- Never run a script that reads student submissions, grades, rosters,
  enrollments, quiz responses or messages.
  Today that means [`studentwork.py`](studentwork.py).
  Only the instructor runs it, by hand.
- Never read the output of such a script, or open the files it downloads.
- A new script that reads student records starts with a comment saying so,
  as `studentwork.py` does, and is added to the list above.
- Scripts agents may run touch course content only:
  assignments, assignment groups, pages, modules, announcements, files and calendar events.
  Never pass an `include[]` value, a `student_id` or a `user_id`,
  which can fold student data into an otherwise safe response.
  [`Morrison-Lab/canvas`](https://github.com/Morrison-Lab/canvas) lists the endpoints this rules out.

## Canvas writes

Students see a change to the live course the moment it lands.
Run [`canvas/sync_assignments.py`](canvas/sync_assignments.py) as a dry run first,
and add `--apply` only after the instructor approves that run.

## Canvas token

The instructor's token lives in their Mac keychain, as item `canvas-token`.
Scripts read it themselves; never print it, copy it into a file or an environment, or ask for it in chat.
