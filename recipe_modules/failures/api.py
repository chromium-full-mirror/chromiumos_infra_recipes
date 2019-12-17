# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for raising failures and presenting them in cute ways."""

from PB.chromiumos.common import ImageType
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2

import collections
import contextlib
import operator

from recipe_engine import recipe_api


class FailuresApi(recipe_api.RecipeApi):
  """A module for presenting errors and raising StepFailures."""

  # A failure in recipe execution.
  #
  # Fields:
  #   kind (str): Describes the kind of failure, e.g. 'build'
  #   title (str): Full title of the failure.
  #   link_map (str->str): title to URL map for the failed task.
  #   fatal (bool): Whether or not the failure is fatal. Fatal failures cause
  #       recipes to fail when the failure is aggregated.
  #   id (str): a unique, reproducible name for this failure. For build-type
  #       failures, this is the builder name.
  Failure = collections.namedtuple('Failure',
                                   ['kind', 'title', 'link_map', 'fatal', 'id'])

  def __init__(self, properties, *args, **kwargs):
    super(FailuresApi, self).__init__(*args, **kwargs)
    self._disable_silences = properties.disable_silences

  def _get_silence_reason(self, step_name):
    """Query SoM to see if the step was silenced.

    Args:
      step_name (str): A full step name, e.g.
        "build results|[FAILED] chromeos.bucket.builder"

    Return:
      A str explaining the silence, or None if there is no silence on the step.
    """
    if self._disable_silences:
      return None

    # TODO(crbug.com/903414): Remove ignore exceptions once calling SoM is
    # stable.
    with self.ignore_exceptions():
      annotation = self.m.cros_som.get_annotation(step_name)

      if annotation is None:
        return None

      return self.m.cros_som.get_silence_reason(annotation)

  def _proto_to_step_status(self, proto_status):
    """Convert from common_pb2.Status to api.step status.

    Args:
      status (common_pb2.Status): status of the step.

    Returns:
      str representing status as listed in step/api.py.
    """
    if proto_status == common_pb2.SUCCESS:
      return self.m.step.SUCCESS
    elif proto_status == common_pb2.INFRA_FAILURE:
      return self.m.step.EXCEPTION
    else:
      return self.m.step.FAILURE

  def _present_run(self, title, link_map, status, critical=True):
    with self.m.step.nest(title) as step:
      if status != common_pb2.SUCCESS and not critical:
        step.presentation.step_text = 'failed but is not critical'
        step.presentation.status = self.m.step.SUCCESS
      else:
        step.presentation.status = self._proto_to_step_status(status)
      for link_text, link_url in link_map.items():
        step.presentation.links[link_text] = link_url

      silence_reason = self._get_silence_reason(self.m.step.active_result.name)
      if silence_reason:
        # Sheriff-o-Matic monitors failed steps, so we cannot modify the
        # step name because it is silenced. For example, imagine the step
        # "build results|[FAILED] chromeos.bucket.builder" is failing and
        # silenced in SoM. If in the next run we change the step name to
        # "build results|[FAILED BUT SILENCED] chromeos.bucket.builder",
        # there will be a new (unsilenced) failure, and the old (silenced)
        # failure will disappear from SoM.
        step.presentation.logs['silence reason'] = [silence_reason]

      return silence_reason is not None

  def _get_failures(self, kind, runs, get_status, is_critical, get_title,
                    get_link_map, get_id):
    with self.m.step.nest('{} results'.format(kind)) as results_step:
      critical_failures = []
      failed_runs = [
          run for run in runs if get_status(run) != common_pb2.SUCCESS
      ]
      silenced_failure_count = 0
      only_infra_failure = True

      for failed_run in sorted(failed_runs, key=get_title):
        title = get_title(failed_run)
        link_map = get_link_map(failed_run)
        fail_id = get_id(failed_run)
        status = get_status(failed_run)
        critical = is_critical(failed_run)

        silenced = self._present_run(title, link_map, status, critical)
        if silenced:
          silenced_failure_count += 1
        only_infra_failure &= (status == common_pb2.INFRA_FAILURE)

        if critical:
          critical_failures.append(
              self.Failure(kind=kind, title=title, link_map=link_map,
                           fatal=not silenced, id=fail_id))

      success_runs = [run for run in runs if run not in failed_runs]
      for success_run in sorted(success_runs, key=get_title):
        title = get_title(success_run)
        link_map = get_link_map(success_run)
        status = get_status(success_run)

        self._present_run(title, link_map, status)

      success_count = len(success_runs)

      if not critical_failures:
        status = self.m.step.SUCCESS
        step_text = 'all critical {}s succeeded'.format(kind)
        if silenced_failure_count:  #pragma: no cover
          step_text += ' ({} failures were silenced)'.format(
              silenced_failure_count)
      else:
        status = self.m.step.EXCEPTION if only_infra_failure else self.m.step.FAILURE
        fail_count = len(failed_runs) - silenced_failure_count
        step_text = '{} {}s failed, {} succeeded, {} failures silenced'.format(
            fail_count, kind, success_count, silenced_failure_count)

      results_step.presentation.status = status
      results_step.presentation.step_text = step_text
      return critical_failures

  def _get_baseline_validated_failures(self, kind, runs, baseline_runs,
                                       get_status, is_critical, get_title,
                                       get_link_map, get_id):
    """Wraps _get_failures() to enable baseline filtering.

    Args:
      kind(str): A text description of runs.
      runs(list[SkylabResult|Build]): List of results.
      baseline_runs(list[SkylabResult|Build]): List of results
        from baseline runs.
      get_status(func): A func(run->STATUS) returns the status of the run.
      is_critical(func): A func(run->bool) returns the criticality of the run.
      get_title(func): A func(run->str) returns the name of the run.
      get_link_map(func): A func(run->map) returns the link map of the run.
      get_id(func): A func (run->str) returns the id of the run.
    """
    failed_baseline_run_names = set([
        get_title(run)
        for run in baseline_runs
        if get_status(run) != common_pb2.SUCCESS
    ])
    filtered_runs = [
        run for run in runs if get_title(run) not in failed_baseline_run_names
    ]
    failures = self._get_failures(kind, filtered_runs, get_status, is_critical,
                                  get_title, get_link_map, get_id)
    if baseline_runs:
      self._get_failures('baseline ' + kind, baseline_runs, get_status,
                         lambda x: True, get_title, get_link_map, get_id)
    return failures

  @contextlib.contextmanager
  def ignore_exceptions(self):
    """Catches exceptions and logs them instead.

    Should only be used temporarily to prevent new features from crashing the
    entire recipe. Remove once new feature is stable.
    """
    try:
      yield
    except Exception as e:
      step = self.m.step('ignored exception', cmd=None)
      step.presentation.logs['caught exception'] = [repr(e)]

  def raise_failed_packages(self, packages):
    """Display failed packages and raise a failure.

    Each package will be shown as a failed substep.

    Args:
      packages (list[chromiumos.common.PackageInfo]): The failed packages.

    Raises:
      StepFailure: If failed_packages is not empty.
    """
    # TODO(evanhernandez): Migrate this function to use _get_failures for
    # better SoM reporting.
    with self.m.step.nest('installation results') as step:
      if not packages:
        step.presentation.step_text = 'all packages installed successfully'
        return

      if len(packages) == 1:
        message = 'failed to install {}'.format(
            self.m.naming.get_package_title(packages[0]))
      else:
        message = 'failed to install {} packages'.format(len(packages))
      step.presentation.step_text = message
      step.presentation.status = self.m.step.FAILURE
      step.presentation.logs['list of failed packages'] = map(
          self.m.naming.get_package_title, packages)
      raise self.m.step.StepFailure(message)

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
    with self.m.step.nest('image test results') as step:
      if not failed_images:
        step.presentation.step_text = 'all images passed'
        return

      message = '{} images failed'.format(len(failed_images))
      step.presentation.step_text = message
      step.presentation.status = self.m.step.FAILURE
      failed_types = map(lambda image: ImageType.Name(image.type),
                         failed_images)
      step.presentation.logs['list of failed images'] = failed_types
      raise self.m.step.StepFailure(message)

  def aggregate_failures(self, failures):
    """Returns a recipe result based on the given failures.

    Only fatal failures cause the whole recipe to fail.

    Args:
      failures (list[Failure]): All failures encountered during execution.

    Returns:
      RawResult: The recipe result, including a human-readable failure summary.
    """
    failures = [failure for failure in failures if failure.fatal]

    # If there were no fatal failures, then the recipe succeeded and there is
    # no need for a summary.
    if not failures:
      return result_pb2.RawResult(status=common_pb2.SUCCESS)

    # Otherwise, we need to create a detailed failure summary.
    failures_by_kind = collections.defaultdict(list)
    for failure in failures:
      failures_by_kind[failure.kind].append(failure)

    # The summary markdown will look roughly as follows:
    #
    # 1 build failed:
    # - chromeos.cq.nami-cq: <a>build page<\a>
    #
    # 2 hw tests failed
    # - hw.coral.bvt-cq: <a>Graphics_Something<\a>
    # - hw.coral.bvt-tast-cq: <a>Cheets_SomethingElse<\a>
    # ...
    summary_lines = []
    for kind in sorted(failures_by_kind):
      failure_group = sorted(failures_by_kind[kind],
                             key=operator.attrgetter('title'))
      count = len(failure_group)
      lines = ['{} {} failed'.format(count, kind + 's' if count > 1 else kind)]

      truncate_max = 10
      failures_to_print = failure_group[0:truncate_max]
      for failure in failures_to_print:
        line = '- {}:'.format(failure.title)
        for link_text, link_url in failure.link_map.items():
          line += ' [{}]({})'.format(link_text, link_url)
        lines.append(line)
      if count > truncate_max:
        lines.append('- ...and {} others'.format(count - truncate_max))
      summary_lines.extend(lines)

    # Truncate the list of failures per section to keep the summary under
    # Buildbucket's 4000 byte limit on the summary_markdown field.
    summary_markdown = ''
    for line in summary_lines:
      if len(summary_markdown) + len(line) < 3990:
        summary_markdown += ('\n\n' + line)
      else:
        # Abruptly truncate to avoid INFRA_FAILURE.
        summary_markdown += ('\n\n...')
        break

    summary_markdown = summary_markdown.strip()
    return result_pb2.RawResult(status=common_pb2.FAILURE,
                                summary_markdown=summary_markdown)

  def get_build_failures(self, builds):
    """Verify all builds completed successfully.

    Args:
      builds (list[build_pb2.Build]): List of completed builds.

    Returns:
      list[Failure]: All failures discovered in the given runs.
    """
    get_id = lambda b: b.builder.builder
    return self._get_failures(
        'build', builds, self.get_build_status, self.m.buildbucket.is_critical,
        self.m.naming.get_build_title, self.m.urls.get_build_link_map, get_id)

  def get_hw_test_failures(self, hw_tests, baseline_hw_tests=None):
    """Logs hardware test status to UI, and raises on failed tests.

    Args:
      hw_tests (list[SkylabResult]): List of Skylab suite results.
      baseline_hw_tests (list[SkylabResult]): List of Skylab suite
        results from the baseline tests.

    Returns:
      list[Failure]: All failures discovered in the given runs filtered
      by baseline failures.
    """
    get_id = self.m.naming.get_skylab_result_title
    return self._get_baseline_validated_failures(
        'hw test', hw_tests, baseline_hw_tests or [], self.get_hwtest_status,
        self.is_hw_test_critical, self.m.naming.get_skylab_result_title,
        self.m.urls.get_skylab_result_link_map, get_id)

  def get_vm_test_failures(self, vm_tests, baseline_vm_tests=None):
    """Logs VM test status to UI, and raises on failed tests.

    Args:
      vm_tests (list[Build]): List of VM test buildbucket results.
      baseline_vm_tests (list[Build]): List of VM test buildbucket results
        from the baseline tests.

    Returns:
      list[Failure]: All failures discovered in the given runs filtered
      by baseline failures.
    """
    get_id = self.m.naming.get_vm_test_title
    return self._get_baseline_validated_failures(
        'vm test', vm_tests, baseline_vm_tests or [], self.get_build_status,
        self.m.buildbucket.is_critical, self.m.naming.get_vm_test_title,
        self.m.urls.get_vm_test_link_map, get_id)

  def get_moblab_vm_test_failures(self, moblab_vm_tests,
                                  baseline_moblab_vm_tests=None):
    """Logs Moblab VM test status to UI, but does not rais on failed tests.

    Args:
      moblab_vm_tests (list[Build]): List of Moblab VM test buildbucket results.
      baseline_moblab_vm_tests (list[Build]): List of Moblab VM test
        buildbucket results from the baseline tests.

    Returns:
      list[Failure]: All failures discovered in the given runs filtered
      by baseline failures.
    """
    get_id = self.m.naming.get_moblab_vm_test_title
    return self._get_baseline_validated_failures(
        'moblab vm test', moblab_vm_tests, baseline_moblab_vm_tests or [],
        self.get_build_status, self.m.buildbucket.is_critical,
        self.m.naming.get_moblab_vm_test_title,
        self.m.urls.get_vm_test_link_map, get_id)

  def get_build_status(self, build):
    """Retrieve the status of the build.

    Args:
      build (Build): The buildbucket Build in question.

    Returns:
      status (common_pb2.Status) of the build.
    """
    return build.status

  def is_critical_test_failure(self, test):
    """Determine if the test is critical and has failed.

    Args:
      test (Build|SkylabResult): The test in question.

    Returns:
      bool: True if the test is critical and has failed.
    """
    if isinstance(test, build_pb2.Build):
      return self.is_critical_vm_test_failure(test)
    elif isinstance(test, self.m.skylab.SkylabResult):
      return self.is_critical_hw_test_failure(test)
    else:
      raise TypeError('expected Build or SkylabResult,' 'got %s' % type(test))

  def get_hwtest_status(self, hw_test):
    """Get the status of the hw_test.

    Args:
      hw_test (SkylabResult): The hardware test result in question.

    Returns:
      status (common_pb2.STATUS) of the test.
    """
    return hw_test.status

  def is_hw_test_critical(self, hw_test):
    """Determine if the vm test was critical.

    Args:
      hw_test (SkylabResult): The hardware test result in question.

    Returns:
      bool: True if the test was critical.
    """
    return hw_test.task.test.common.critical.value

  def is_critical_build_failure(self, build):
    """Determine in the build failed and was critical.

    Args:
      build (Build): The buildbucket build in question.

    Returns:
      bool: True if the build failed and was critical.
    """
    return (self.get_build_status(build) != common_pb2.SUCCESS and
            self.m.buildbucket.is_critical(build))

  def is_critical_hw_test_failure(self, hw_test):
    """Determine if the vm test failed and was critical.

    Args:
      hw_test (SkylabResult): The hardware test result in question.

    Returns:
      bool: True if the test failed and was critical.
    """
    return (self.get_hwtest_status(hw_test) != common_pb2.SUCCESS and
            hw_test.task.test.common.critical.value)

  def is_critical_vm_test_failure(self, vm_test):
    """Determine if the vm test failed and was critical.

    Args:
      vm_test (Build): The buildbucket build for the VM test.

    Returns:
      bool: True if the test failed and was critical
    """
    return self.is_critical_build_failure(vm_test)

  def is_critical_moblab_vm_test_failure(self, moblab_vm_test):
    """Determine if the vm test failed and was critical.

    Args:
      moblab_vm_test (Build): The buildbucket build for the Moblab VM test.

    Returns:
      bool: True if the test failed and was critical
    """
    return self.is_critical_build_failure(moblab_vm_test)

  def update_non_critical_failures(self, step, failures, fresh_builder_configs):
    """

    Args:
      failures (list[Failure]): All failures encountered during execution.
      step (recipe Step): parent step.
      fresh_builder_configs (dict(str, BuilderConfig)): name to builder config
          for all BuilderConfigs that should have criticality checked.

    Returns:
      list[Failure]: the updated list of builders with 'fatal' statuses
          possibly updated.
    """
    new_failures = []
    presentation_log = []
    for f in failures:
      fatal = f.fatal
      if f.kind == 'build':
        if f.id in fresh_builder_configs:
          cfg = fresh_builder_configs[f.id]
          non_critical = cfg.general.critical and not cfg.general.critical.value
          if f.fatal and non_critical:
            presentation_log.append('changed {} to non-critical'.format(f.id))
            fatal = False
      new_failures.append(
          self.Failure(kind=f.kind, title=f.title, link_map=f.link_map,
                       fatal=fatal, id=f.id))
    if presentation_log:
      step.presentation.logs['new non-critical builders'] = presentation_log
    return new_failures
