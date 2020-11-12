# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for PUpr."""

from PB.recipes.chromeos.generator import (
    RetryClPolicy,
    NO_RETRY,
    RETRY_LATEST_OR_LATEST_PINNED,
    RETRY_LATEST_PINNED,
)

from recipe_engine import recipe_api

import re

FAILED_RE = re.compile("^Patch Set \d+:\s*Failed builds")
RUNNING_RE = re.compile("^Patch Set \d+:\s*CQ is trying the patch")


def is_failed_cl(c):
  """ Determine if the CL in question is in a failed state. """
  # c.messages is sorted in ascending order of date. Reverse to get most recent first.
  for m in reversed(c.messages):
    if FAILED_RE.match(m["message"]):
      return True
  return False


def is_running_cl(c):
  """ Determine if the CL in question is in a running state. """
  # c.messages is sorted in ascending order of date. Reverse to get most recent first.
  for m in reversed(c.messages):
    # If we hit a try message before a failed message, the change
    # hasn't failed yet for the most recent run.
    if RUNNING_RE.match(m["message"]):
      return True
    if FAILED_RE.match(m["message"]):
      break
  return False


class PuprApi(recipe_api.RecipeApi):
  """A module for PUpr steps."""
  HASHTAG_FREEZE_RETRIES = "pupr-freeze-retries"
  HASHTAG_PINNED_RETRY = "pupr-retry-pinned"

  def retries_frozen(self, changes):
    """Examine open CLs for the HASHTAG_FREEZE_RETRIES hashtag.

    Args:
      changes (List[gerrit.PatchSet]): List of CLs.

    Returns:
      bool: Whether or not a HASHTAG_FREEZE_RETRIES hashtag is present.
    """
    return any([self.HASHTAG_FREEZE_RETRIES in c.hashtags for c in changes])

  def identify_retry(self, retry_policy, open_cls):
    """Identify the CL to be retried based on retry_policy.

    Args:
      retry_policy (RetryClPolicy): The retry policy to follow. Can be NO_RETRY,
        LATEST_OR_LATEST_PINNED, or LATEST_PINNED.
      open_cls (List[gerrit.PatchSet]): List of CLs.

    Returns:
      PatchSet: The CL to be retried (or None if no retry)
    """
    if retry_policy not in [RETRY_LATEST_OR_LATEST_PINNED, RETRY_LATEST_PINNED]:
      return None

    # Look for open cl with hashtag HASHTAG_PINNED_RETRY
    retry_cl = None
    for cl in open_cls:
      if self.HASHTAG_PINNED_RETRY in cl.hashtags:
        retry_cl = cl
        break

    # If we haven't identified a pinned CL and the retry policy is not RETRY_PINNED_ONLY,
    # find most recent failed CL.
    # TODO(crbug/1148822): Add support for Dry Run CLS
    if retry_policy != RETRY_LATEST_PINNED and not retry_cl:
      # Filter out CLs that haven't failed (i.e. been tried at least once)
      failed_cl = list(filter(is_failed_cl, open_cls))

      if failed_cl:
        # Sort to get most recent failed
        failed_cl.sort(key=lambda cl: cl.created, reverse=True)
        retry_cl = failed_cl[0]

    # Only want to retry a CL that has previously failed and s not currently running.
    if retry_cl and is_failed_cl(retry_cl) and not is_running_cl(retry_cl):
      return retry_cl
    return None
