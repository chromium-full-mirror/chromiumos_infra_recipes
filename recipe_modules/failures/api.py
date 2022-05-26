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

from recipe_engine.recipe_api import RecipeApi, StepFailure


class FailuresApi(RecipeApi):
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
  #       failures, this is the builder name. For test-type failures this is the
  #       display_name.
  Failure = collections.namedtuple('Failure',
                                   ['kind', 'title', 'link_map', 'fatal', 'id'])

  def __init__(self, *args, **kwargs):
    super(FailuresApi, self).__init__(*args, **kwargs)

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
    with self.m.step.nest(title) as presentation:
      if status != common_pb2.SUCCESS and not critical:
        presentation.step_text = 'failed but is not critical'
        presentation.status = self.m.step.SUCCESS
      else:
        presentation.status = self._proto_to_step_status(status)
      for link_text, link_url in link_map.items():
        presentation.links[link_text] = link_url
      return

  def _get_failures(self, kind, runs, get_status, is_critical, get_title,
                    get_link_map, get_id):
    with self.m.step.nest('{} results'.format(kind)) as results_pres:
      critical_failures = []
      failed_runs = [
          run for run in runs if get_status(run) != common_pb2.SUCCESS
      ]
      only_infra_failure = True

      for failed_run in sorted(failed_runs, key=get_title):
        title = get_title(failed_run)
        link_map = get_link_map(failed_run)
        fail_id = get_id(failed_run)
        status = get_status(failed_run)
        critical = is_critical(failed_run)

        self._present_run(title, link_map, status, critical)
        only_infra_failure &= (status == common_pb2.INFRA_FAILURE)

        if critical:
          critical_failures.append(
              self.Failure(kind=kind, title=title, link_map=link_map,
                           fatal=True, id=fail_id))

      success_runs = [run for run in runs if run not in failed_runs]
      for success_run in sorted(success_runs, key=get_title):
        title = get_title(success_run)
        link_map = get_link_map(success_run)
        status = get_status(success_run)

        self._present_run(title, link_map, status)

      if not critical_failures:
        status = self.m.step.SUCCESS
        step_text = 'all critical {}s succeeded'.format(kind)
      else:
        status = self.m.step.EXCEPTION if only_infra_failure else self.m.step.FAILURE
        step_text = '{} {}s failed, {} succeeded'.format(
            len(failed_runs), kind, len(success_runs))

      results_pres.status = status
      results_pres.step_text = step_text
      return critical_failures

  @contextlib.contextmanager
  def ignore_exceptions(self):
    """Catches exceptions and logs them instead.

    Should only be used temporarily to prevent new features from crashing the
    entire recipe. Remove once new feature is stable.
    """
    try:
      yield
    except Exception as e:  # pylint: disable=broad-except
      step = self.m.step('ignored exception', cmd=None)
      step.presentation.logs['caught exception'] = [repr(e)]

  def set_failed_packages(self, enclosing_step, packages):
    """If any failed packages, set presentation and raise failure.

    Args:
      enclosing_step (step): The enclosing step to mutate.
      packages (list[tuple[chromiumos.common.PackageInfo, str]]): The failed
        packages.

    Raises:
      StepFailure: If failed_packages is not empty.
    """
    if not packages:
      return

    if len(packages) == 1:
      long_message = 'failed to install {}'.format(
          self.m.naming.get_package_title(packages[0][0]))
    else:
      long_message = 'failed to install {} packages'.format(len(packages))

    enclosing_step.presentation.step_text = long_message
    enclosing_step.presentation.status = self.m.step.FAILURE
    enclosing_step.presentation.logs['list of failed packages'] = map(
        self.m.naming.get_package_title, [p[0] for p in packages])
    for p in packages:
      if not p[1]:
        continue
      enclosing_step.presentation.logs['%s/%s log' % (p[0].category,
                                                      p[0].package_name)] = p[1]
    raise StepFailure(long_message)

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
      failed_types = [ImageType.Name(image.type) for image in failed_images]
      presentation.logs['list of failed images'] = failed_types
      raise StepFailure(message)

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

  def get_build_failures(self, builds, refresh_configs=False):
    """Verify all builds completed successfully.

    Args:
      builds (list[build_pb2.Build]): List of completed builds.
      refresh_configs (bool): Whether to update configs and adjust is_critical.

    Returns:
      list[Failure]: All failures discovered in the given runs.
    """
    get_id = lambda b: b.builder.builder
    ret = self._get_failures('build', builds, self.get_build_status,
                             self.m.buildbucket.is_critical,
                             self.m.naming.get_build_title,
                             self.m.urls.get_build_link_map, get_id)
    if refresh_configs:
      self.m.cros_infra_config.force_reload()
      child_configs = self.m.cros_infra_config.safe_get_builder_configs(
          [b.builder.builder for b in builds])
      ret = self.update_non_critical_build_failures(ret, child_configs)
    return ret

  def get_hw_test_failures(self, hw_tests):
    """Logs hardware test status to UI, and raises on failed tests.

    Args:
      hw_tests (list[SkylabResult]): List of Skylab suite results.

    Returns:
      list[Failure]: All failures discovered in the given runs filtered
      by baseline failures.
    """
    get_id = self.m.naming.get_skylab_result_title
    return self._get_failures('hw test', hw_tests, self.get_hwtest_status,
                              self.is_hw_test_critical,
                              self.m.naming.get_skylab_result_title,
                              self.m.urls.get_skylab_result_link_map, get_id)

  def get_vm_test_failures(self, vm_tests):
    """Logs VM test status to UI, and raises on failed tests.

    Args:
      vm_tests (list[Build]): List of VM test buildbucket results.

    Returns:
      list[Failure]: All failures discovered in the given runs filtered
      by baseline failures.
    """
    get_id = self.m.naming.get_vm_test_title
    return self._get_failures('vm test', vm_tests, self.get_build_status,
                              self.m.buildbucket.is_critical,
                              self.m.naming.get_vm_test_title,
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
      return self.is_critical_build_failure(test)
    elif isinstance(test, self.m.skylab.SkylabResult):
      return self.is_critical_hw_test_failure(test)
    else:
      raise StepFailure('expected Build or SkylabResult,' 'got %s' % type(test))

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

  @contextlib.contextmanager
  def _with_step(self, step, name):
    """Returns a context with the current step, or a new one.

    Args:
      step (StepData): The current step, or None.
      name (str): The name of the step to create if there is not one.

    Returns:
      (context) with active step.
    """
    if step:
      yield step
    else:
      with self.m.step.nest(name) as step:
        yield step

  def update_non_critical_build_failures(self, failures, fresh_builder_configs,
                                         presentation=None):
    """If builders are now non-critical or removed, failures are non-fatal.

    Args:
      failures (list[Failure]): All failures encountered during execution.
      fresh_builder_configs (dict(str, BuilderConfig)): name to builder config
          for all BuilderConfigs that should have criticality checked.
      presentation (StepPresentation): Parent step presentation.  If None, a
          StepPresentation will be created.

    Returns:
      updated_failures (list[Failure]): The list of Failures with 'fatal'
          statuses possibly updated.
    """
    updated_failures = []
    new_non_critical_builds = []
    for f in failures:
      fatal = f.fatal
      if f.kind == 'build':
        if f.id in fresh_builder_configs:
          cfg = fresh_builder_configs[f.id]
          non_critical = cfg.general.critical and not cfg.general.critical.value
        else:
          # Deleted builders are non_critical.
          non_critical = True
        if f.fatal and non_critical:
          new_non_critical_builds.append(f.id)
          fatal = False
      updated_failures.append(
          self.Failure(kind=f.kind, title=f.title, link_map=f.link_map,
                       fatal=fatal, id=f.id))
    if new_non_critical_builds:
      with self._with_step(presentation, 'non-critical build check') as pres:
        pres.logs['new non-critical builders'] = new_non_critical_builds
    return updated_failures

  def update_non_critical_test_failures(self, failures, test_plan_summary,
                                        presentation=None):
    """If tests are now non-critical, failures are non-fatal.

    Args:
      failures (list[Failure]): All failures encountered during execution.
      test_plan_summary (dict{string: bool}): Map of test display name to
        criticality against which to check test failures.
      presentation (StepPresentation): Parent step presentation.  If None, a
          StepPresentation will be created.

    Returns:
      updated_failures (list[Failure]): The list of Failures with 'fatal'
        statuses possibly updated.
    """
    updated_failures = []
    new_non_critical_tests = []

    for f in failures:
      # Skip build and non-fatal failures.
      if not f.kind.endswith('test') or not f.fatal:
        updated_failures.append(f)
        continue

      # Deleted tests are considered critical. The planner may have different
      # options, and choose one test in the first plan, a second test in the
      # second plan; to err on the side of caution, assume that if a test is not
      # explicitly marked non-critical, it is still critical.
      critical = test_plan_summary.get(f.id, True)
      if not critical:
        new_non_critical_tests.append(f.id)
        updated_failures.append(
            self.Failure(kind=f.kind, title=f.title, link_map=f.link_map,
                         fatal=critical, id=f.id))
      else:
        updated_failures.append(f)

    if new_non_critical_tests:
      with self._with_step(presentation, 'non-critical test check') as pres:
        pres.logs['new non-critical tests'] = new_non_critical_tests
    return updated_failures

  def format_step_failures(self, step_failures):
    """Helper function to format the collected failures for presentation.

    Args:
      step_failures (list[Failure]): Collected error messages from exceptions.
    Returns:
      formatted markdown string for UI presentation.
    """
    markdown = ""
    if step_failures:
      lines = [
          "{} step{} failed:\n".format(
              len(step_failures), "" if len(step_failures) == 1 else "s")
      ]
      for failure in step_failures:
        lines += ["- %s\n" % failure.reason or failure.name]

      # truncate markdown to 4K to avoid INFRA_FAILURE
      markdown = lines[0]
      for line in lines[1:]:
        if len(markdown) + len(line) < 3990:
          markdown += '\n\n' + line
        else:  #pragma: nocover
          markdown += '\n\n...'
          break
    return markdown
