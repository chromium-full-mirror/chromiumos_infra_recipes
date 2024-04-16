#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This file contains the staging builders (and associated configs) used for
qualifying recipes releases."""

import re
import typing
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Tuple


class StagingReCheck(typing.NamedTuple):
  """A tuple containing the project, builder and regex used to search."""
  project: str
  bucket: str
  regex: str
  # exemptions can turn failures into successes.
  # The input is a dict parsed from the `bb ls` output, e.g.
  # {"id":"8782723488170713857","builder":{"project":"chromeos", ...
  # The output should be True if the failure can be ignored.
  exemptions: List[Callable[[Dict[str, Any]], bool]] = []
  # Number of builds to check.
  num_builds: int = 5

  @property
  def name(self) -> Tuple[str]:
    return (self.project, self.bucket, self.regex)

  def __eq__(self, other):
    return self.name == other.name

  def __hash__(self):
    return hash(self.name)


def orchestrator_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for orchestrator builds."""
  ignorable_summary_markdown_re = [
      re.compile(r'\d+ out of \d+ builds? failed'),
      re.compile(r'\d+ hw tests? failed'),
      re.compile(r'\d+ hw test suites? failed'),
      re.compile(r'\d+ vm tests? failed'),
      re.compile(r'\d+ vm test suites? failed'),
  ]
  for regex in ignorable_summary_markdown_re:
    if regex.search(build.get('summaryMarkdown', '')):
      return True
  return False


def image_builder_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for image builds."""
  if build.get('status') == 'INFRA_FAILURE':
    return False

  ignorable_summary_markdown_re = [
      re.compile(r'^failed unit tests for'),
      re.compile(r'^failed compilation for'),
      re.compile(
          r"^Step\('build images\.test images\.call chromite\.api\.ImageService/Test\.call build API script'\) \(retcode: 3\)$"
      ),
  ]
  for regex in ignorable_summary_markdown_re:
    if regex.search(build.get('summaryMarkdown', '')):
      return True
  return False


def build_firmware_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for failures during the `build_firmware` step."""
  if build.get('status') == 'INFRA_FAILURE':
    return False
  summary = build.get('summaryMarkdown', '')
  return "Step('build firmware.call build API script')" in summary


def autoreleaser_no_releasable_changes_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for autoreleaser builds with no releasable changes."""
  return build.get('summaryMarkdown').startswith('No releasable changes found')


def sdk_update_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for SDK update failures."""
  ignorable_summary_markdown_re = [
      re.compile('call chromite.api.SdkService/Update.call build API script'),
  ]
  for regex in ignorable_summary_markdown_re:
    if regex.search(build.get('summaryMarkdown', '')):
      return True
  return False


def cq_cancelled_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for CQ builds cancelled by CV."""
  ignorable_cancellation_markdown = 'LUCI CV no longer needs this Tryjob'
  return build.get('cancellationMarkdown',
                   '') == ignorable_cancellation_markdown


def merge_conflict_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for CQ builds that hit merge conflicts."""
  ignorable_summary_markdown_re = [
      re.compile(r'^Merge conflict detected!'),
  ]
  for regex in ignorable_summary_markdown_re:
    if regex.search(build.get('summaryMarkdown', '')):
      return True
  return False


# TODO(b/299105459): Remove once paygen local signing is stable.
def atlas_signingnext_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for paygen-orchs/paygen builds from the prototype
    staging-atlas-signingnext builder.

    See b/299105459 for more context.
  """
  if build['input']['properties'].get('builder_name') == 'atlas-signingnext':
    return True
  # Catch-all so we don't have to traverse deep into `paygen` properties.
  if 'atlas-signingnext' in str(build['input']['properties']):
    return True

  # Also filter out all split paygen builds, as those are still experimental.
  if build['input']['properties'].get('recipe') in [
      'paygen_orchestrator', 'paygen'
  ] and build['input']['properties'].get('use_split_paygen', False):
    return True
  return False


INFRA_BUNDLE_STAGING_CHECKS_RE = (
    StagingReCheck('chromeos', 'staging', r'LegacyNoopSuccess', num_builds=3),
    StagingReCheck('chromeos', 'staging', r'staging-amd64-generic-postsubmit',
                   [image_builder_exemption], num_builds=2),
    StagingReCheck('chromeos', 'staging', r'staging-Annealing'),
    StagingReCheck('chromeos', 'staging', r'staging-chrome-pupr-generator',
                   num_builds=3),
    StagingReCheck('chromeos', 'staging', r'staging-cop', num_builds=2),
    StagingReCheck('chromeos', 'staging', r'staging-cq-auto-retrier'),
    StagingReCheck('chromeos', 'staging', r'staging-cq-orchestrator', [
        orchestrator_exemption, cq_cancelled_exemption, merge_conflict_exemption
    ], num_builds=20),
    StagingReCheck('chromeos', 'staging', r'staging-DutTracker'),
    StagingReCheck('chromeos', 'staging', r'staging-firmware-ti50-postsubmit',
                   [image_builder_exemption, build_firmware_exemption]),
    StagingReCheck('chromeos', 'staging', r'staging-manifest-doctor',
                   num_builds=3),
    StagingReCheck('chromeos', 'staging', r'staging-recipes_autoreleaser_infra',
                   [autoreleaser_no_releasable_changes_exemption],
                   num_builds=1),
    StagingReCheck('chromeos', 'staging', r'staging-RoboCrop'),
    StagingReCheck('chromeos', 'staging', r'staging_SourceCacheBuilder'),
    StagingReCheck('chromeos', 'staging', r'staging-StarDoctor'),
    StagingReCheck('chromeos', 'staging', r'staging-(?!.*llfg).*-incremental$',
                   [image_builder_exemption, sdk_update_exemption],
                   num_builds=2),
    StagingReCheck('chromeos', 'staging', r'staging-brancher', num_builds=3),
)

RELEASE_BUNDLE_STAGING_CHECKS_RE = (
    StagingReCheck('chromeos', 'staging',
                   r'staging-release-R(?P<milestone>\d+)-\d+\.B-orchestrator'),
    # Branched staging only runs once daily, as opposed to ToT which runs 4
    # times a day. We're enforcing 5 builds on ToT, so we can probably afford
    # to check fewer of the branched builders.
    StagingReCheck('chromeos', 'staging',
                   r'staging-octopus-release-R(?P<milestone>\d+)-\d+\.B',
                   [image_builder_exemption], num_builds=3),
    StagingReCheck('chromeos', 'staging',
                   r'staging-zork-release-R(?P<milestone>\d+)-\d+\.B',
                   [image_builder_exemption], num_builds=3),
    StagingReCheck('chromeos', 'staging', r'staging-paygen',
                   [atlas_signingnext_exemption], num_builds=125),
    StagingReCheck('chromeos', 'staging', r'staging-paygen-orchestrator',
                   [atlas_signingnext_exemption], num_builds=15),
    StagingReCheck('chromeos', 'staging', r'staging-release-main-orchestrator'),
    StagingReCheck('chromeos', 'staging', r'staging-release-triggerer',
                   num_builds=3),
    # TODO(b/278066948): When lts staging runs are replicated, enable checking them.
    # StagingReCheck('chromeos', 'staging', 'staging-release-R\d+-\d+\.B-cq-orchestrator'),
)
