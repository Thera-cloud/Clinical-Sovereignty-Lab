-- G3 fix: seed the 20-problem MIT-licensed HumanEval subset into ln7_tasks
-- so the real (non-stub) public benchmark harness (ln7_public_harness.run_humaneval_benchmark)
-- can record_outcome() against them without hitting the ln7_coding_outcomes FK constraint.
-- split=eval keeps these permanently excluded from the training feedback loop
-- (see assert_train_eligible() in ln7_ledger.py).
-- Idempotent: also self-healed at runtime by _ensure_humaneval_tasks_seeded().

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/0', 'public', 'medium', '6ca1b771b5077b380d761a73cc40b23a7042d0514937fda754f15d9087494ed8', 'eval', 'MIT', NULL, 'from typing import List


def has_close_elements(numbers: List[float], threshold: float) -> bool:
    """ Check if in given list of numbers, are any two numbers closer to each other than
    given thr', '{"benchmark": "humaneval", "entry_point": "has_close_elements"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/7', 'public', 'medium', '51f470c92b14d243e905885347ceb4b46fe7d761682936a5b5c5591e65158576', 'eval', 'MIT', NULL, 'from typing import List


def filter_by_substring(strings: List[str], substring: str) -> List[str]:
    """ Filter an input list of strings only for ones that contain given substring
    >>> filter_by', '{"benchmark": "humaneval", "entry_point": "filter_by_substring"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/14', 'public', 'medium', '6ad5e8ff983327e462be71b6d413bc2b4a0f9fd997f5f29193012fa9d8db0ea8', 'eval', 'MIT', NULL, 'from typing import List


def all_prefixes(string: str) -> List[str]:
    """ Return list of all prefixes from shortest to longest of the input string
    >>> all_prefixes(''abc'')
    [''a'', ''ab'', ''abc''', '{"benchmark": "humaneval", "entry_point": "all_prefixes"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/21', 'public', 'medium', '50aaf869450bf86b1f487e1a612cbd3facb3c6c8e89d6fce7aed9548bebe59f3', 'eval', 'MIT', NULL, 'from typing import List


def rescale_to_unit(numbers: List[float]) -> List[float]:
    """ Given list of numbers (of at least two elements), apply a linear transform to that list,
    such that the s', '{"benchmark": "humaneval", "entry_point": "rescale_to_unit"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/28', 'public', 'medium', 'dcdf2f447c4454d9761d2da9ba7a5d138ab114ee2f220d5d05aa366020cb912b', 'eval', 'MIT', NULL, 'from typing import List


def concatenate(strings: List[str]) -> str:
    """ Concatenate list of strings into a single string
    >>> concatenate([])
    ''''
    >>> concatenate([''a'', ''b'', ''c''])
    ''', '{"benchmark": "humaneval", "entry_point": "concatenate"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/35', 'public', 'medium', '036f1209a0b07b598dca5362d81356063856d83446a8d937db5a20d286ba0857', 'eval', 'MIT', NULL, '

def max_element(l: list):
    """Return maximum element in the list.
    >>> max_element([1, 2, 3])
    3
    >>> max_element([5, 3, -5, 2, -3, 3, 9, 0, 123, 1, -10])
    123
    """
', '{"benchmark": "humaneval", "entry_point": "max_element"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/42', 'public', 'medium', '8bc9ba8d16960cedbdc41ed913455aa14dc237d408d6331b2baffcff22045ed3', 'eval', 'MIT', NULL, '

def incr_list(l: list):
    """Return list with elements incremented by 1.
    >>> incr_list([1, 2, 3])
    [2, 3, 4]
    >>> incr_list([5, 3, 5, 2, 3, 3, 9, 0, 123])
    [6, 4, 6, 3, 4, 4, 10, 1, 1', '{"benchmark": "humaneval", "entry_point": "incr_list"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/49', 'public', 'medium', 'b5ce3e910f90b3aede300dcb0f29da1ea0ee503c6dc4e248ade7ec887f9bba27', 'eval', 'MIT', NULL, '

def modp(n: int, p: int):
    """Return 2^n modulo p (be aware of numerics).
    >>> modp(3, 5)
    3
    >>> modp(1101, 101)
    2
    >>> modp(0, 101)
    1
    >>> modp(3, 11)
    8
    >>> modp(', '{"benchmark": "humaneval", "entry_point": "modp"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/56', 'public', 'medium', 'ae6e475a6e12be40ce8f1ab669d8ff273a3ff1027af00a24d843f7f5b2881542', 'eval', 'MIT', NULL, '

def correct_bracketing(brackets: str):
    """ brackets is a string of "<" and ">".
    return True if every opening bracket has a corresponding closing bracket.

    >>> correct_bracketing("<")
   ', '{"benchmark": "humaneval", "entry_point": "correct_bracketing"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/63', 'public', 'medium', 'd94c3d49798c5717d22aafd285f36e48a4c730532e72d19b50d09aebdefe9773', 'eval', 'MIT', NULL, '

def fibfib(n: int):
    """The FibFib number sequence is a sequence similar to the Fibbonacci sequnece that''s defined as follows:
    fibfib(0) == 0
    fibfib(1) == 0
    fibfib(2) == 1
    fibfib(', '{"benchmark": "humaneval", "entry_point": "fibfib"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/70', 'public', 'medium', 'f62330a48f69de30ca39a1e4298737aa74154170e3202b44c13ec41d8d276044', 'eval', 'MIT', NULL, '
def strange_sort_list(lst):
    ''''''
    Given list of integers, return list in strange order.
    Strange sorting, is when you start with the minimum value,
    then maximum of the remaining integers', '{"benchmark": "humaneval", "entry_point": "strange_sort_list"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/77', 'public', 'medium', 'dc268a26b31fd4a0358a9c17276c7f961f74b08c013f4a9f9892fae4771d1d75', 'eval', 'MIT', NULL, '
def iscube(a):
    ''''''
    Write a function that takes an integer a and returns True 
    if this ingeger is a cube of some integer number.
    Note: you may assume the input is always valid.
    Exa', '{"benchmark": "humaneval", "entry_point": "iscube"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/84', 'public', 'medium', 'a8a4c7e956038f759de5178649f1ef1c60e59e93a60bb105711c0c3858d537e5', 'eval', 'MIT', NULL, '
def solve(N):
    """Given a positive integer N, return the total sum of its digits in binary.
    
    Example
        For N = 1000, the sum of digits will be 1 the output should be "1".
        For', '{"benchmark": "humaneval", "entry_point": "solve"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/91', 'public', 'medium', '8c433e39263504c1e123c9fe184b5b893d2264e9e5148887b697e412a0144116', 'eval', 'MIT', NULL, '
def is_bored(S):
    """
    You''ll be given a string of words, and your task is to count the number
    of boredoms. A boredom is a sentence that starts with the word "I".
    Sentences are delimite', '{"benchmark": "humaneval", "entry_point": "is_bored"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/98', 'public', 'medium', '416a4dc84bb9c8335634fcbd812bfb229a79410e7e90f3f77074e84ed86d829e', 'eval', 'MIT', NULL, '
def count_upper(s):
    """
    Given a string s, count the number of uppercase vowels in even indices.
    
    For example:
    count_upper(''aBCdEf'') returns 1
    count_upper(''abcdefg'') returns 0
', '{"benchmark": "humaneval", "entry_point": "count_upper"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/105', 'public', 'medium', '2e54b098c51111e859231156e7c0c0c521e3a2a935b2eca544ce8add37f23c85', 'eval', 'MIT', NULL, '
def by_length(arr):
    """
    Given an array of integers, sort the integers that are between 1 and 9 inclusive,
    reverse the resulting array, and then replace each digit by its corresponding nam', '{"benchmark": "humaneval", "entry_point": "by_length"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/112', 'public', 'medium', '31b642e7c63666d2c3bef6df1c352daaef3ffaa9bf0e2efdf95982d0ecf96b9a', 'eval', 'MIT', NULL, '
def reverse_delete(s,c):
    """Task
    We are given two strings s and c, you have to deleted all the characters in s that are equal to any character in c
    then check if the result string is pali', '{"benchmark": "humaneval", "entry_point": "reverse_delete"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/119', 'public', 'medium', 'c49b165429072843d3c9d2e2dec752872f62290ddf43a25f20a32c16a4daa5bd', 'eval', 'MIT', NULL, '
def match_parens(lst):
    ''''''
    You are given a list of two strings, both strings consist of open
    parentheses ''('' or close parentheses '')'' only.
    Your job is to check if it is possible to c', '{"benchmark": "humaneval", "entry_point": "match_parens"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/126', 'public', 'medium', '575f1a70df4deed3219fe7cc727160c9c401bb01737a268c2d0b4fcee8fb3f92', 'eval', 'MIT', NULL, '
def is_sorted(lst):
    ''''''
    Given a list of numbers, return whether or not they are sorted
    in ascending order. If list has more than 1 duplicate of the same
    number, return False. Assume n', '{"benchmark": "humaneval", "entry_point": "is_sorted"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;

INSERT INTO ln7_tasks (task_id, source, difficulty, task_hash, split, spdx_license, pack_name, prompt_summary, metadata_json)
VALUES ('HumanEval/133', 'public', 'medium', '0be536efc81fa89b957ebb6283068f76ed770026ad08c7d524a346146b84b0dd', 'eval', 'MIT', NULL, '

def sum_squares(lst):
    """You are given a list of numbers.
    You need to return the sum of squared numbers in the given list,
    round each element in the list to the upper int(Ceiling) first.', '{"benchmark": "humaneval", "entry_point": "sum_squares"}'::jsonb)
ON CONFLICT (task_id) DO NOTHING;
