# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from collections import namedtuple
import json

from recipe_engine import post_process

from PB.chromiumos.common import Chroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.chromiumos.common import UseFlag
from PB.chromite.api import depgraph
from PB.chromite.api.sysroot import InstallPackagesRequest
from PB.chromite.api.sysroot import Sysroot
from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties
from PB.recipe_modules.chromeos.chrome.examples.test import TestInputProperties
from RECIPE_MODULES.chromeos.gerrit.api import PatchSet

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'chrome',
    'cros_build_api',
    'gerrit',
]


PROPERTIES = TestInputProperties


def jsonify(**kwargs):
  """Return the kwargs as a json string."""
  return json.dumps(kwargs)


def RunSteps(api, properties):

  # TODO(1098567): Add method to gerrit/test_api.py to generate patch_sets, and
  # add a test to confirm that 9999 and 86.0.1234.0_rc-r2.ebuild hits.
  def patch_set(files):
    """Return a patchset.

    Args:
      files (list[str]): list of modified files.

    Returns:
      A PatchSet.
    """
    project = 'chromiumos/overlays/chromiumos-overlay'
    return PatchSet({
        'host': 'test',
        'info': {
            'project': project
        },
        'patch_set': '3',
        'patch_set_revision': 'f000' * 10,
        'revision_info': {
            'files': {f: {} for f in files}
        }
    })

  chroot = Chroot()
  build_target = BuildTarget(name='target')
  sysroot = Sysroot(path='/build/sysroot', build_target=build_target)

  # There isn't a protobuf definition for PatchSet, so we create it here.
  need_ps = patch_set([
      'chromeos-base/chromeos-chrome/chromeos-chrome-9999.ebuild',
      'some/path/that/isnt/important'
  ])
  no_need_ps = patch_set(['some/path/that/isnt/important'])

  ps_list = [need_ps if properties.changes else no_need_ps]

  dep_graph = namedtuple('_dep_graph', ['target', 'sdk'])(depgraph.DepGraph(
      sysroot=sysroot, build_target=build_target, package_deps=[
          depgraph.PackageDepInfo(
              package_info=PackageInfo(category='chromeos-base',
                                       package_name='chromeos-chrome',
                                       version='85.0.4148.0_rc-r1'),
              dependency_packages=[
                  PackageInfo(category='chromeos-base',
                              package_name='chrome-icu',
                              version='85.0.4148.0_rc-r1'),
              ]),
          depgraph.PackageDepInfo(
              package_info=PackageInfo(category='virtual',
                                       package_name='chromeos-interface',
                                       version='1-r5'),
              dependency_packages=[
                  PackageInfo(category='chromeos-base',
                              package_name='chromeos-chrome',
                              version='85.0.4148.0_rc-r1'),
                  PackageInfo(category='chromeos-base',
                              package_name='chromeos-login',
                              version='0.0.2-r4356')
              ]),
      ]), depgraph.DepGraph())

  internal = UseFlag(flag='chrome_internal')
  request = InstallPackagesRequest(
      chroot=chroot, sysroot=sysroot, packages=properties.packages,
      use_flags=None if properties.external else [internal],
      flags=InstallPackagesRequest.Flags(
          compile_source=properties.ignore_prebuilts))

  with api.step.nest('check chrome source needed') as step:
    source_needed = api.chrome.needs_chrome_source(request, dep_graph, step,
                                                   patch_sets=ps_list)
  api.assertions.assertEqual(source_needed, properties.expected_builds_from)
  if source_needed:
    api.chrome.sync(
        chrome_root=api.path.start_dir / 'chrome', chroot=chroot,
        build_target=build_target, internal=not properties.external,
        cache_dir=api.path.start_dir.joinpath('chrome').joinpath('cache'),
        omit_version=api.properties.get('omit_version') or False)


def GenTests(api):

  def test_data(skips_chrome_prebuilt=False, needs_chrome=True, changes=True,
                expected_builds_from=True, chrome_prebuilt=False, **kwargs):
    # TODO(crbug/1086714): We don't have NeedsChromeSource yet, so force
    # disable_needs_chrome=True.
    kwargs['disable_needs_chrome'] = True
    props = TestInputProperties(needs_chrome=needs_chrome, changes=changes,
                                expected_builds_from=expected_builds_from,
                                **kwargs)

    def api_response(name, data, step_name=None):
      """Add Build API response.

      Args:
        name (str): API name, such as 'PackageService/HasPrebuilt'.
        data (str): JSON data to return from Build API.
        step_name (str): Name of the sub-step, or None.

      Returns:
        StepTestData
      """
      return api.step_data(
          'check chrome source needed%s.call chromite.api.'
          '%s.read output file' % ('.' + step_name if step_name else '', name),
          api.file.read_raw(content=data))

    ret = api.properties(props)
    if props.disable_needs_chrome:
      ret += api.cros_build_api.remove_endpoints(
          ['PackageService/NeedsChromeSource'])
      ret += api_response('PackageService/BuildsChrome',
                          jsonify(builds_chrome=needs_chrome))
      if needs_chrome:
        ret += api_response('PackageService/HasPrebuilt',
                            jsonify(has_prebuilt=not expected_builds_from),
                            step_name='any followers lack prebuilts')

      if not props.ignore_prebuilts and not skips_chrome_prebuilt:
        ret += api_response('PackageService/HasChromePrebuilt',
                            jsonify(has_prebuilt=chrome_prebuilt))
    # TODO(crbug/1086714): We don't have NeedsChromeSource yet.  Remove the
    # pragma:nocover when we do.
    else:  # pragma: nocover
      reasons = []
      if props.needs_chrome:
        reasons.extend(['COMPILE_SOURCE'] if props.ignore_prebuilts else [])
        reasons.extend(['LOCAL_UPREV'] if props.changes else [])
        reasons.extend([] if chrome_prebuilt else ['NO_PREBUILT'])
      ret += api_response(
          'PackageService/NeedsChromeSource',
          jsonify(needsChromeSource=(len(reasons) > 0), reasons=reasons))

    return ret

  yield api.test(
      'basic',
      test_data(chrome_prebuilt=False),
  )

  yield api.test(
      'basic-no-version',
      test_data(chrome_prebuilt=False),
      api.properties(omit_version=True),
      api.post_check(post_process.StepCommandDoesNotContain,
                     'sync chrome.gclient sync', ['--version']),
      api.post_check(post_process.DoesNotRun,
                     'chromite.api.PackageService/GetChromeVersion'),
  )

  yield api.test(
      'no-changes',
      test_data(changes=False, chrome_prebuilt=True,
                expected_builds_from=False),
  )

  chrome_cas = ChromeProperties(version='deadbeef',
                                deps_cas=ChromeProperties.DepsCas(digest='aaa'))

  yield api.test(
      'with-properties-custom-build-cas',
      test_data(skips_chrome_prebuilt=True),
      api.properties(**{'$chromeos/chrome': chrome_cas}),
  )

  # TODO(crbug/1086714): _old_test_data and test cases that follow should be
  # removed once they are no longer needed. (Sometime after 2021-01-01.)
  def _old_test_data(**kwargs):
    """Helper to reduce the need for typing."""
    return test_data(disable_needs_chrome=True, **kwargs)

  yield api.test(
      'no-changes-old',
      _old_test_data(changes=False, chrome_prebuilt=True,
                     expected_builds_from=False),
  )

  yield api.test(
      'ignore-prebuilts-old',
      _old_test_data(ignore_prebuilts=True),
  )
