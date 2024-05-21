# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for raising image builder failures and presenting them."""

import re
from typing import List, Optional, Tuple
from google.protobuf import json_format

from PB.chromiumos import common as common_pb2
from PB.recipe_modules.chromeos.failures.failures import PackageFailure
from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution \
  import CqFailureAttribute

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.post_process_inputs import Step
from recipe_engine.recipe_api import StepFailure


class ImageBuilderFailuresApi(RecipeApi):
  """A module for presenting errors and raising StepFailures."""

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self._package_failures = []

  @property
  def package_failures(self):
    return self._package_failures

  def _add_snapshot_fault_attribution(
      self, package_failures: List[PackageFailure]) -> List[PackageFailure]:
    """Populate the snapshot_comparison field for CQ PackageFailures."""

    # This only applies to CQ child builds.
    if not self.m.buildbucket.build.builder.builder.endswith('-cq'):
      return package_failures

    snapshot_builder_name = re.sub('(-slim)?-cq$', '-snapshot',
                                   self.m.buildbucket.build.builder.builder)

    predicate = builds_service_pb2.BuildPredicate(
        builder=builder_common_pb2.BuilderID(
            builder=snapshot_builder_name, project='chromeos', bucket='staging'
            if self.m.cros_infra_config.is_staging else 'postsubmit'),
        tags=self.m.cros_tags.tags(snapshot=self.m.src_state.gitiles_commit.id))

    # This is best-effort and should not obscure the original failure.
    try:
      builds = self.m.buildbucket.search(
          predicate, limit=1, url_title_fn=self.m.naming.get_build_title)
    except StepFailure:
      return package_failures

    # TODO(b/328542826): Consider comparing to the previous snapshot if the
    # current one has not yet completed or was not relevant.
    if len(builds) != 1:
      return package_failures

    snapshot_build_output_dict = json_format.MessageToDict(
        builds[0].output.properties)
    snapshot_package_failures = [
        json_format.ParseDict(x, PackageFailure())
        for x in snapshot_build_output_dict.get('package_failures', [])
    ]
    # Clear the version as it may differ (e.g. package upreved during CQ run).
    for p in snapshot_package_failures:
      p.package.version = ''

    for p in package_failures:
      # Only compare the PackageInfo (without version) and the phase.
      if PackageFailure(
          package=common_pb2.PackageInfo(package_name=p.package.package_name,
                                         category=p.package.category),
          phase=p.phase) in snapshot_package_failures:
        p.snapshot_comparison = CqFailureAttribute.MATCHING_FAILURE_FOUND

    return package_failures

  def _set_failed_packages(
      self, enclosing_step: Step,
      packages: List[Tuple[common_pb2.PackageInfo, str]], compile_failure: bool,
      cl_affected_packages: Optional[List[common_pb2.PackageInfo]] = None):
    """If any failed packages, set presentation and raise failure.

    Args:
      enclosing_step: The enclosing step to mutate.
      packages: The failed packages.
      compile_failure: Whether this was a compilation failure.
      cl_affected_packages: The packages which are affected by the changes under
        test.

    Raises:
      StepFailure: If failed_packages is not empty.
    """
    cl_affected_packages = cl_affected_packages or []

    def _concat_package_markdown_link(package_info, log_text):
      # If the package did not produce a log, just return the name.
      if not log_text:
        return self.m.naming.get_package_title(package_info)

      log_name = '%s_%s_log' % (package_info.category,
                                package_info.package_name)
      log_url = self.m.urls.get_logdog_url(self.m.step.active_result, log_name)
      markdown_link = '[%s](%s)' % (
          self.m.naming.get_package_title(package_info), log_url)

      return markdown_link

    # Return early if there were no failed packages.
    if not packages:
      return

    packages.sort(key=lambda p: p[0].package_name)
    # Create top-level links to the list of failed packages as well as to the
    # Portage logs for the failed packages.
    enclosing_step.logs['list of failed packages'] = map(
        self.m.naming.get_package_title, [p[0] for p in packages])
    for p in packages:
      if not p[1]:
        continue
      enclosing_step.logs['%s/%s log' %
                          (p[0].category, p[0].package_name)] = p[1]

    failed_package_names = [
        self.m.naming.get_package_title(p[0]) for p in packages
    ]
    failed_packages_links = [
        _concat_package_markdown_link(p[0], p[1]) for p in packages
    ]

    if compile_failure:
      error_reason_text = 'failed compilation for'
    else:
      error_reason_text = 'failed unit tests for'

    if len(packages) == 1:
      step_text = '%s %s' % (error_reason_text, failed_package_names[0])
      failure_message = '%s %s' % (error_reason_text, failed_packages_links[0])
    else:
      step_text = '{} {} packages: {}'.format(error_reason_text, len(packages),
                                              ', '.join(failed_package_names))
      summary_lines = [
          '{} {} packages'.format(error_reason_text, len(packages))
      ]
      for p in failed_packages_links:
        summary_lines.append('- {}'.format(p))
      failure_message = self.m.failures.format_summary_markdown(summary_lines)

    package_failures = [
        PackageFailure(
            package=p[0], phase=PackageFailure.COMPILE
            if compile_failure else PackageFailure.TEST,
            affected_by_changes=p[0] in cl_affected_packages) for p in packages
    ]
    package_failures = self._add_snapshot_fault_attribution(package_failures)

    self._package_failures.extend(package_failures)
    enclosing_step.properties['package_failures'] = [
        json_format.MessageToDict(p) for p in package_failures
    ]
    enclosing_step.status = self.m.step.FAILURE
    enclosing_step.step_text = step_text
    raise StepFailure(failure_message)

  def set_test_failed_packages(
      self, enclosing_step: Step, packages: List[Tuple[common_pb2.PackageInfo,
                                                       str]],
      cl_affected_packages: Optional[List[common_pb2.PackageInfo]] = None):
    """If any packages failed unit tests set presentation and raise failure.

    Args:
      enclosing_step: The enclosing step to mutate.
      packages: The failed packages.
      cl_affected_packages: The packages which are affected by the changes under
        test.

    Raises:
      StepFailure: If failed_packages is not empty.
    """
    return self._set_failed_packages(
        enclosing_step,
        packages,
        False,
        cl_affected_packages,
    )

  def set_compile_failed_packages(
      self, enclosing_step: Step, packages: List[Tuple[common_pb2.PackageInfo,
                                                       str]],
      cl_affected_packages: Optional[List[common_pb2.PackageInfo]] = None):
    """If any packages failed compilation set presentation and raise failure.

    Args:
      enclosing_step: The enclosing step to mutate.
      packages: The failed packages.
      cl_affected_packages: The packages which are affected by the changes under
        test.

    Raises:
      StepFailure: If failed_packages is not empty.
    """
    return self._set_failed_packages(
        enclosing_step,
        packages,
        True,
        cl_affected_packages,
    )

  def raise_failed_image_tests(self, failed_images):
    """Display failed image tests and raise a failure.

    Displays the images that failed tests and raises a failure if there
    are failed image tests. If there are no failed image tests, a success
    message is output.

    Args:
      failed_images: (list[chromite.image.Image]): The images that failed
          tests.

    Raises:
      StepFailure: If failed_images is not empty.
    """
    with self.m.step.nest('image test results') as presentation:
      if not failed_images:
        presentation.step_text = 'all images passed'
        return

      message = '{} images failed'.format(len(failed_images))
      presentation.step_text = message
      presentation.status = self.m.step.FAILURE
      failed_types = [
          common_pb2.ImageType.Name(image.type) for image in failed_images
      ]
      presentation.logs['list of failed images'] = failed_types
      raise StepFailure(message)
