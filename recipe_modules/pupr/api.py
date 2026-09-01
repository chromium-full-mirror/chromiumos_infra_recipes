# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for PUpr."""

import dataclasses
from enum import Enum
import json
import re
from typing import Generic, List, Tuple, TypeVar, overload

from PB.chromite.api import packages as packages_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipes.chromeos.generator import (
    DRY_RUN,
    DRY_RUN_NOT_APPROVED,
    FULL_RUN,
    RETRY_LATEST_OR_LATEST_PINNED,
    RETRY_LATEST_PINNED,
)
from recipe_engine import recipe_api

from RECIPE_MODULES.chromeos.gerrit.api import PatchSet

T = TypeVar('T')


def format_gerrit_change_link(c: GerritChange) -> str:
  """Format a GerritChange proto into a clickable markdown link."""
  if c.host in ('chromium', 'chromium-review.googlesource.com'):
    return f'[chromium:{c.change}](https://crrev.com/c/{c.change})'
  if c.host in ('chrome-internal', 'chrome-internal-review.googlesource.com'):
    return f'[chrome-internal:{c.change}](https://crrev.com/i/{c.change})'
  return str(c.change)


@dataclasses.dataclass(frozen=True)
class StepResult(Generic[T]):
  """Result of a PUpr step containing its primary return value and side-effects."""
  value: T = None
  created: list[GerritChange] = dataclasses.field(default_factory=list)
  retried: list[GerritChange] = dataclasses.field(default_factory=list)
  abandoned: list[GerritChange] = dataclasses.field(default_factory=list)
  errors: list[str] = dataclasses.field(default_factory=list)
  warnings: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Result:
  """Aggregator for PUpr operations and final status / markdown evaluation."""
  created: list[GerritChange] = dataclasses.field(default_factory=list)
  retried: list[GerritChange] = dataclasses.field(default_factory=list)
  abandoned: list[GerritChange] = dataclasses.field(default_factory=list)
  cleanup_errors: list[str] = dataclasses.field(default_factory=list)
  fatal_errors: list[str] = dataclasses.field(default_factory=list)
  warnings: list[str] = dataclasses.field(default_factory=list)
  errors: list[str] = dataclasses.field(default_factory=list)
  no_action_reason: str | None = None

  @overload
  def record(self, step_result: StepResult[T]) -> T:
    ...  # pragma: no cover

  @overload
  def record(self, step_result: 'Result') -> None:
    ...  # pragma: no cover

  def record(self, step_result: StepResult[T] | 'Result') -> T | None:
    """Record a StepResult or Result into this aggregator."""
    if isinstance(step_result, Result):
      self.created.extend(step_result.created)
      self.retried.extend(step_result.retried)
      self.abandoned.extend(step_result.abandoned)
      self.cleanup_errors.extend(step_result.cleanup_errors)
      self.fatal_errors.extend(step_result.fatal_errors)
      self.warnings.extend(step_result.warnings)
      self.errors.extend(step_result.errors)
      if step_result.no_action_reason and not self.no_action_reason:
        self.no_action_reason = step_result.no_action_reason
      return None
    self.created.extend(step_result.created)
    self.retried.extend(step_result.retried)
    self.abandoned.extend(step_result.abandoned)
    self.cleanup_errors.extend(step_result.errors)
    self.warnings.extend(step_result.warnings)
    return step_result.value

  def evaluate(self, is_retry_only: bool = False) -> tuple[int, str]:
    """Determine the buildbucket status (SUCCESS/FAILURE) and markdown summary.

    Special Rule:
    1. If CL creation passes: cleanup errors are demoted to warnings (build is SUCCESS).
    2. If retry-only run: cleanup errors are promoted to errors (build is FAILURE).
    """
    warnings = list(self.warnings)
    errors = list(self.errors)

    if self.fatal_errors:
      errors.extend(self.fatal_errors)

    if not is_retry_only and self.created:
      # Creation succeeded, cleanup errors become warnings
      warnings.extend(self.cleanup_errors)
    else:
      # In retry-only runs, or runs without successful creation, cleanup errors are errors
      errors.extend(self.cleanup_errors)

    status = bb_common_pb2.FAILURE if errors else bb_common_pb2.SUCCESS
    prefix = '[retry-only] ' if is_retry_only else ''

    if errors:
      headline = f'{prefix}failed: {errors[0]}'
    elif self.no_action_reason:
      headline = f'{prefix}no action ({self.no_action_reason})'
    else:
      headline = f'{prefix}success'

    lines = [headline]

    if self.created:
      lines.append('\n### Created CLs')
      for c in self.created:
        lines.append(f'* {format_gerrit_change_link(c)}')

    if self.retried:
      lines.append('\n### Retried CLs')
      for c in self.retried:
        lines.append(f'* {format_gerrit_change_link(c)}')

    if self.abandoned:
      lines.append('\n### Abandoned CLs')
      for c in self.abandoned:
        lines.append(f'* {format_gerrit_change_link(c)}')

    if warnings:
      lines.append('\n### Warnings')
      for w in warnings:
        lines.append(f'* {w}')

    if errors:
      lines.append('\n### Errors')
      for e in errors:
        lines.append(f'* {e}')

    return status, '\n'.join(lines)

DRY_RUN_TAG_RE = re.compile('^autogenerated:c[qv]:dry-run(:.*)?$')
FULL_RUN_TAG_RE = re.compile('^autogenerated:c[qv]:full-run(:.*)?$')

FAILED_RE = re.compile(
    r'^Patch Set \d+:\s*(Failed builds:|This CL has failed the run\. Reason:)')
RUNNING_RE = re.compile(r'^Patch Set \d+:\s*C[QV] is trying the patch')
# Won't be used in practice (because submitted changes won't be in the open change set),
# but included for symmetry's sake.
PASSED_RE = re.compile(
    r'^Patch Set \d+:\s*Change has been successfully rebased and submitted')
# CLs on this doesn't have votes satisfying submit requirement and should be ignored from full run retry.
IGNORE_RE = re.compile(
    r'^Patch Set \d+:\s*CV cannot start a Run because this CL is not satisfying .* submit requirement.'
)


FAILED_DRY_RUN_RE = re.compile(r'^Patch Set \d+:\s*(Dry run: Failed builds|'
                               r'This CL has failed the run\. Reason:)')
RUNNING_DRY_RUN_RE = re.compile(
    r'^Patch Set \d+:\s*Dry run: C[QV] is trying the patch')
PASSED_DRY_RUN_RE = re.compile(
    r'^Patch Set \d+:\s*(Dry run: This CL passed the C[QV] dry run|'
    r'This CL has passed the run)')

# Magic hashtag to specify that PUpr for the given package is frozen.
HASHTAG_FREEZE_RETRIES = 'pupr-freeze-retries'
# Magic hashtag to give a specific PUpr CL priority.
HASHTAG_PINNED_RETRY = 'pupr-retry-pinned'
# Magic hashtag to mark a CL as ignored by PUpr.
HASHTAG_IGNORED = 'pupr-ignored'

# The label written in the commit message to store versions information of
# upstream repositories given by gitiles trigger.
UPREV_VERSION_LABEL = 'Pupr-Upstream-Versions'


# TODO(b/543713972): Use a trigger proto (e.g., GitilesTrigger) instead of
# packages_pb2.UprevVersionedPackageRequest.GitRef for serializing and
# deserializing upstream version metadata stored in commit message footers.
def deserialize_versions(
    json_str: str) -> list[packages_pb2.UprevVersionedPackageRequest.GitRef]:
  """Deserialize versions information.

  Args:
    json_str: A string serialized by serialize_versions().

  Returns:
    The versions to consider for an uprev.
  """
  objs = json.loads(json_str)
  return [
      packages_pb2.UprevVersionedPackageRequest.GitRef(
          repository=o.get('repository'), ref=o.get('ref'),
          revision=o.get('revision')) for o in objs
  ]


class RunState(Enum):
  RUNNING = 1
  FAILED = 2
  PASSED = 3


def get_patterns(dry_run):
  """
  Get appropriate tag/regexes for the CQ mode (CQ+1 or CQ+2).
  """
  if dry_run:
    return (DRY_RUN_TAG_RE, FAILED_DRY_RUN_RE, RUNNING_DRY_RUN_RE,
            PASSED_DRY_RUN_RE)
  return (FULL_RUN_TAG_RE, FAILED_RE, RUNNING_RE, PASSED_RE)


def is_failed_cl(c, dry_run=False):
  """
  Determine if the CL in question's most recent result is failed for the given
  run type (full or dry). If the most recent state was of the other run type or
  is of the given run type but is not failed, this function will return False.
  """
  return is_cl_in_state(c, RunState.FAILED, dry_run)


def is_running_cl(c, dry_run=False):
  """
  Determine if the CL in question's most recent result is running for the given
  run type (full or dry). If the most recent state was of the other run type or
  is of the given run type but is not running, this function will return False.
  """
  if c.labels is not None:
    label_info = c.labels.get('Commit-Queue', {})
    if 'all' in label_info:
      val = 1 if dry_run else 2
      return any(x.get('value') == val for x in label_info.get('all', []))
  return is_cl_in_state(c, RunState.RUNNING, dry_run)


def is_passed_cl(c, dry_run=False):
  """
  Determine if the CL in question's most recent result is passed for the given
  run type (full or dry). If the most recent state was of the other run type or
  is of the given run type but is not passed, this function will return False.
  """
  return is_cl_in_state(c, RunState.PASSED, dry_run)


def is_cl_in_state(c, desired_state, dry_run=False):
  """
  Determine if the CL in question's most recent state is the desired state
  for a full/dry run. If the most recent state was of the other run type or
  is of the given run type but is not the desired state, this function will
  return False.
  """
  run_tag_re, failed_re, running_re, passed_re = get_patterns(dry_run)
  all_state_res = (failed_re, running_re, passed_re)
  inverse_run_tag_re, _, _, _ = get_patterns(not dry_run)

  desired_state_re = {
      RunState.RUNNING: running_re,
      RunState.PASSED: passed_re,
      RunState.FAILED: failed_re,
  }.get(desired_state)
  undesired_state_res = [state_re for state_re in all_state_res \
    if state_re != desired_state_re]

  for m in sorted(c.messages, key=lambda m: m['date'], reverse=True):
    if 'tag' not in m:
      continue
    # If the most recent run is of the other run type (full/dry), then the CL
    # is not in the desired state for this run type.
    if inverse_run_tag_re.match(m['tag']):
      return False
    # If the tag is neither a dry run tag nor a full run tag, try the next one.
    if not run_tag_re.match(m['tag']):
      continue  # pragma: nocover

    # If we encounter a message that CV cannot start, ignore this CL.
    if not dry_run and IGNORE_RE.match(m['message']):
      return False
    # If we encounter a message of the desired type, then the CL is in that
    # state for this run type.
    if desired_state_re.match(m['message']):
      return True
    # Else if we encounter a message of any of the undesired types, then the CL
    # is not in that state for this run type.
    if any(re.match(m['message']) for re in undesired_state_res):
      return False
  return False


def sorted_cls(cls):
  """Return cls sorted by create date, descending."""
  return sorted(cls, key=lambda cl: cl.created, reverse=True)


def count_running_cls(open_patch_sets: List[PatchSet]) -> int:
  """Count how many of the open patch sets are currently running CQ."""
  running_count = 0
  for ps in open_patch_sets:
    if is_running_cl(ps, dry_run=True) or is_running_cl(ps, dry_run=False):
      running_count += 1
  return running_count


class PuprApi(recipe_api.RecipeApi):
  """A module for PUpr steps."""

  Result = Result
  StepResult = StepResult

  @staticmethod
  def format_gerrit_change_link(c: GerritChange) -> str:
    """Format a GerritChange proto into a clickable markdown link."""
    return format_gerrit_change_link(c)

  @staticmethod
  def extract_upstream_git_refs(
      description: str,
  ) -> list[packages_pb2.UprevVersionedPackageRequest.GitRef] | None:
    """Extract upstream git refs from a commit message description.

    Args:
      description: The commit message description.

    Returns:
      The deserialized upstream GitRef list, or None if no upstream version
      metadata is present.

    Raises:
      recipe_api.StepFailure: If multiple UPREV_VERSION_LABEL footers are found.
    """
    matches = re.findall(UPREV_VERSION_LABEL + r': (.*)', description)
    if len(matches) > 1:
      raise recipe_api.StepFailure(
          f'Found multiple {UPREV_VERSION_LABEL} footers in Change description')
    if len(matches) == 1:
      return deserialize_versions(matches[0])
    return None

  @staticmethod
  def retries_frozen(changes):
    """Examine open CLs for the HASHTAG_FREEZE_RETRIES hashtag.

    Args:
      changes (List[PatchSet]): List of CLs.

    Returns:
      bool: Whether or not a HASHTAG_FREEZE_RETRIES hashtag is present.
    """
    return any(HASHTAG_FREEZE_RETRIES in c.hashtags for c in changes)

  @staticmethod
  def is_verified_minus_one_cl(c) -> bool:
    """Return whether the CL (PatchSet) has Verified-1 label."""
    if c.labels is not None:
      label_info = c.labels.get('Verified', {})
      if label_info.get('value') == -1:
        return True
      if any(x.get('value') == -1 for x in label_info.get('all', [])):
        return True  # pragma: nocover
    return False

  @staticmethod
  def supports_verified_label(c) -> bool:
    """Return whether the CL's project supports the Verified label."""
    return c.labels is None or 'Verified' in c.labels

  @staticmethod
  def is_cl_ignored(c) -> bool:
    """Return whether the CL (PatchSet) has an ignore hashtag from PUpr."""
    return HASHTAG_IGNORED in c.hashtags

  @staticmethod
  def is_cl_pinned(cl) -> bool:
    """Return if the CL (PatchSet) is pinned."""
    return HASHTAG_PINNED_RETRY in cl.hashtags

  @staticmethod
  def num_full_cq_failures(cl) -> int:
    """Return the number of times the CL (PatchSet) has failed full CQ."""
    return sum(1 for m in cl.messages
               if ('tag' in m and FULL_RUN_TAG_RE.match(m['tag']) and
                   FAILED_RE.match(m['message'])))

  @staticmethod
  def num_dry_run_cq_failures(cl) -> int:
    """Return the number of times the CL (PatchSet) has failed dry-run CQ."""
    return sum(1 for m in cl.messages
               if ('tag' in m and DRY_RUN_TAG_RE.match(m['tag']) and
                   FAILED_RE.match(m['message'])))

  def check_concurrent_cq_limit(
      self, open_patch_sets: List[PatchSet],
      max_concurrent_cq_runs: int) -> Tuple[bool, int]:
    """Check if the concurrent CQ runs limit is reached or exceeded.

    Args:
      open_patch_sets: Open CL patch sets.
      max_concurrent_cq_runs: Max concurrent CQ runs allowed.

    Returns:
      (Whether limit is exceeded, currently running count)
    """
    if max_concurrent_cq_runs <= 0:
      return False, 0
    running_count = count_running_cls(open_patch_sets)
    return running_count >= max_concurrent_cq_runs, running_count

  def identify_retry(self, retry_policy, no_existing_cls_policy, open_cls):
    """Identify the CL to be retried based on retry_policy.

    Precedence order:
      * If a CL is already run for CQ+2, that CL.
        (This means no retry should happen, unless rebase_before_retry is set)
      * If a pinned CL exists, most recent pinned CL if failed, or None if most
          recent pinned CL is not failed.
      * Most recent CL with a passed dry run, if no_existing_cls_policy ==
          FULL_RUN.
      * Most recent CL with a failed full run.
      * Most recent CL with a failed dry run.
      * The latest open CL if no_existing_cls_policy == FULL_RUN.

    Args:
      retry_policy (RetryClPolicy): The retry policy to follow. Can be NO_RETRY,
        LATEST_OR_LATEST_PINNED, or LATEST_PINNED.
      no_existing_cls_policy (SendToCqPolicy): The policy this PUpr builder
        follows when no CL exists. If FULL_RUN, we will look for any successful
        dry runs, allowing us to retry the latest one as a full run. If no
        successful dry run is found or if DRY_RUN, we will look for a failed CL.
        Also, if FULL_RUN, we fallback to retrying the latest open CL.
      open_cls (List[PatchSet]): List of CLs.

    Returns:
      (PatchSet, int, str, bool, bool):
          (The CL to be retried (or None if no retry),
          CQ label to be applied,
          The description of the action,
          Whether the CL, if any, is currently passed,
          Whether the CL, if any, is currently running for CQ+1 or +2)
    """
    if retry_policy not in [RETRY_LATEST_OR_LATEST_PINNED, RETRY_LATEST_PINNED]:
      return (None, 0, 'Not set to retry.', False, False)

    open_cls = [
        cl for cl in open_cls if self.is_cl_pinned(cl) or
        (not self.is_verified_minus_one_cl(cl) and not self.is_cl_ignored(cl))
    ]
    open_cls = sorted_cls(open_cls)

    # Helper functions to generate return value for retry.
    def with_retry(retry_cl, is_dry_run, retry_cl_is_passed):
      return (retry_cl, 1 if is_dry_run else 2,
              'Found cl: {}'.format(retry_cl.display_url), retry_cl_is_passed,
              False)

    def no_retry(message='No open CL was found to retry.'):
      return (None, 0, message, False, False)

    def retry_if_rebase(retry_cl, is_dry_run, retry_cl_is_passed, message):
      return (retry_cl, 1 if is_dry_run else 2, message, retry_cl_is_passed,
              True)

    # Check to see if there is a CL (previously failed or not) currently running with CQ+2.
    # If a CL is in the process of running, no retry will occur except for the case when
    # rebasing it to resolve merge conflict.
    running_cq2_cls = list(filter(is_running_cl, open_cls))
    if running_cq2_cls:
      retry_cl = running_cq2_cls[0]
      return retry_if_rebase(
          retry_cl, False, is_passed_cl(retry_cl, dry_run=True),
          'There are CQ+2 run(s) ongoing: {}'.format(' '.join(
              [cl.display_url for cl in running_cq2_cls])))

    # Pinned CLs (i.e. CLs with the HASHTAG_PINNED_RETRY) take precendence.
    # Here, we looked for the most recent pinned CL.
    for cl in open_cls:
      if PuprApi.is_cl_pinned(cl):
        # (Most recent) pinned CL identified. If the CL has not previously
        # failed, no retry is necessary and we can return.

        # Identify most recent failure type (if any).
        if is_failed_cl(cl):
          return with_retry(cl, False, False)
        if is_failed_cl(cl, dry_run=True):
          return with_retry(cl, True, False)
        # Pinned CL has not failed, do not attempt any retry.
        return no_retry('Pinned retry CL {} has not failed.'.format(
            cl.display_url))

    # If no_existing_cls_policy is FULL_RUN, then CLs that were dry run instead
    # (because a full run was in progress when they were created) and passed
    # their dry run take precedence over retrying failures.
    if no_existing_cls_policy == FULL_RUN:
      retry_cl = next((cl for cl in open_cls if is_passed_cl(cl, dry_run=True)),
                      None)
      if retry_cl:
        return with_retry(retry_cl, False, True)

    # If none exists, find the most recent failed CQ+2 CL, or if none exist
    # then the most recent failed CQ+1 CL if no newer dry run is ongoing, as
    # long as the retry strategy is not RETRY_LATEST_PINNED.
    if retry_policy == RETRY_LATEST_PINNED:
      return no_retry()

    # First look for passed dry runs.
    # Look for CLs with failed full runs first.
    retry_cl = next(iter(filter(is_failed_cl, open_cls)), None)
    if retry_cl:
      return with_retry(retry_cl, False, False)

    # Look for failed dry runs, as long as no newer dry run is ongoing.
    retry_cl = next((c for c in open_cls if is_failed_cl(c, dry_run=True)),
                    None)
    if retry_cl:
      if not any(
          cl for cl in open_cls
          if cl.created > retry_cl.created and is_running_cl(cl, dry_run=True)):
        return with_retry(
            retry_cl, no_existing_cls_policy in [DRY_RUN, DRY_RUN_NOT_APPROVED],
            False)

    # Look for ongoing dry runs, just in case it may need rebasing.
    retry_cl = next((c for c in open_cls if is_running_cl(c, dry_run=True)),
                    None)
    if retry_cl:
      if not any(
          cl for cl in open_cls
          if cl.created > retry_cl.created and is_running_cl(cl, dry_run=True)):
        return retry_if_rebase(
            retry_cl, True, False,
            'Found running cl: {}'.format(retry_cl.display_url))

    if open_cls:
      if no_existing_cls_policy == FULL_RUN:
        return with_retry(open_cls[0], False, False)
      if no_existing_cls_policy in [DRY_RUN, DRY_RUN_NOT_APPROVED]:
        if not is_passed_cl(open_cls[0], dry_run=True):
          return with_retry(open_cls[0], True, False)

    return no_retry()
