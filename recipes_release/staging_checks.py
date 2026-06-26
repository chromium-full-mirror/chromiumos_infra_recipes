#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This file contains the staging builders (and associated configs) used for
qualifying recipes releases."""

import datetime
import re
from typing import Any, Callable, Dict, List, Tuple, NamedTuple


class StagingReCheck(NamedTuple):
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


def test_firmware_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for failures during the `test_firmware` step."""
  if build.get('status') == 'INFRA_FAILURE':
    return False
  summary = build.get('summaryMarkdown', '')
  return "Step('test firmware.call build API script')" in summary


def autoreleaser_no_releasable_changes_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for autoreleaser builds with no releasable changes."""
  summary = build.get('summaryMarkdown', '')
  return summary.startswith('No releasable changes found')


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


# TODO: b/299105459 - Remove once paygen local signing is stable.
def atlas_signingnext_exemption(build: Dict[str, Any]) -> bool:
  """Exempt paygen builds from the staging-atlas-signingnext prototype builder.

  For more context, see b/299105459.
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


# TODO: b/350474581 - Remove after 2024-07-05.
def r120_pushimage_exemption(build: Dict[str, Any]) -> bool:
  """Exempt staging-release-R120 builds that failed during PushImage.

  These builders temporarily failed while calling the build API endpoint
  ImageService/PushImage due to a permissions issue. This issue was resolved on
  2024-07-01 UTC. The fix occurred outside of recipes.

  Since the failures are well-understood, won't affect the production builders,
  and are not caused by a faulty recipes change, this failure mode should not
  block recipes releases.
  """
  if 'release-R120-15662.B' not in build.get('builder', {}).get('builder', ''):
    return False
  if build['createTime'] > datetime.datetime(2024, 7, 1,
                                             tzinfo=datetime.timezone.utc):
    return False
  return 'ImageService/PushImage' in build.get('summaryMarkdown', '')


INFRA_BUNDLE_STAGING_CHECKS_RE = (
    StagingReCheck('chromeos', 'staging',
                   r'staging-amd64-generic-always-relevant-snapshot',
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
    # build_firmware recipe
    StagingReCheck('chromeos', 'staging', 'staging-firmware-zephyr-cq', [
        image_builder_exemption,
        build_firmware_exemption,
        test_firmware_exemption,
    ]),
    StagingReCheck('chromeos', 'staging', 'staging-firmware-zephyr-postsubmit',
                   [
                       image_builder_exemption,
                       build_firmware_exemption,
                       test_firmware_exemption,
                   ]),
    # build_gsc_firmware recipe
    StagingReCheck('chromeos', 'staging', 'staging-firmware-ti50-postsubmit', [
        image_builder_exemption,
        build_firmware_exemption,
        test_firmware_exemption,
    ]),
    # build_legacy_fw recipe
    StagingReCheck('chromeos', 'staging',
                   'staging-firmware-skywalker-16378.B-branch',
                   [image_builder_exemption], num_builds=1),
    StagingReCheck('chromeos', 'staging', 'staging-recipes_autoreleaser_infra',
                   [autoreleaser_no_releasable_changes_exemption],
                   num_builds=1),
    StagingReCheck('chromeos', 'staging', r'staging-RoboCrop'),
    StagingReCheck('chromeos', 'staging', r'staging-StarDoctor'),
    StagingReCheck('chromeos', 'staging', r'staging-(?!.*llfg).*-incremental$',
                   [image_builder_exemption, sdk_update_exemption],
                   num_builds=2),
)

RELEASE_BUNDLE_STAGING_CHECKS_RE = (
    StagingReCheck('chromeos', 'staging',
                   r'staging-release-R(?P<milestone>\d+)-\d+\.B-orchestrator',
                   num_builds=2),
    StagingReCheck('chromeos', 'staging',
                   r'staging-betty-release-R(?P<milestone>\d+)-\d+\.B',
                   [image_builder_exemption, r120_pushimage_exemption],
                   num_builds=2),
    StagingReCheck('chromeos', 'staging',
                   r'staging-atlas-release-R(?P<milestone>\d+)-\d+\.B',
                   [image_builder_exemption, r120_pushimage_exemption],
                   num_builds=2),
    StagingReCheck('chromeos', 'staging', r'staging-paygen-mpa',
                   [atlas_signingnext_exemption], num_builds=20),
    StagingReCheck('chromeos', 'staging', r'staging-paygen-orchestrator-mpa',
                   [atlas_signingnext_exemption], num_builds=10),
    StagingReCheck('chromeos', 'staging', r'staging-manifest-doctor',
                   num_builds=3),
    StagingReCheck('chromeos', 'staging', r'staging-release-main-orchestrator',
                   num_builds=2),
    StagingReCheck('chromeos', 'staging', r'staging-release-triggerer',
                   num_builds=3),
    StagingReCheck('chromeos', 'staging', r'staging-betty-release-main',
                   num_builds=2),
    StagingReCheck('chromeos', 'staging', r'staging-atlas-release-main',
                   num_builds=2),
    # TODO: b/278066948 - When lts staging runs are replicated, enable checking them.
    # StagingReCheck('chromeos', 'staging', 'staging-release-R\d+-\d+\.B-cq-orchestrator'),
    StagingReCheck('chromeos', 'staging', r'staging_SourceCacheBuilder'),
    StagingReCheck('chromeos', 'staging', r'staging-brancher', num_builds=3),
)
