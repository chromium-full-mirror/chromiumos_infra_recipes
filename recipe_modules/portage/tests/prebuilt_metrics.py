#  -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.portage.tests.prebuilt_metrics_test import TestMetricsInputProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'portage',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = TestMetricsInputProperties

_NO_EMERGE_OUTPUT = ''
_BAD_TYPE = 1
_IDEAL_EMERGE_OUTPUT = '''
[binary  N     ] dev-go/errors-0.9.1-r1::chromiumos to /build/eve/ 48 KiB
[binary  N     ] dev-libs/libffi-3.1-r8::chromiumos to /build/eve/ USE="-debug -pax_kernel -static-libs -test" ABI_X86="(64) -32 (-x32)" 230 KiB
[binary  N     ] dev-go/go-spew-1.1.1::chromiumos to /build/eve/ USE="-test" 63 KiB
[binary  N     ] media-libs/libsync-0.0.1-r7::chromiumos to /build/eve/ USE="-cros_host" 48 KiB
[ebuild  N     ] net-libs/libmnl-1.0.4:0/0.2.0::portage-stable to /build/eve/ USE="-examples -split-usr -static-libs" 50 KiB
[binary  N     ] sys-apps/hwdata-0.356-r1::chromiumos to /build/eve/ USE="pci -net -usb" 318 KiB
[ebuild  N     ] sys-apps/sed-4.8::portage-stable to /build/eve/ USE="-acl -nls -selinux -static -verify-sig" 327 KiB
[binary  N     ] dev-go/uuid-1.1.1-r1::chromiumos to /build/eve/ 45 KiB
'''
_PARTIAL_EMERGE_OUTPUT = '''
sdk dev-lang/rust dev-lang/go sys-libs/glibc sys-devel/gcc' virtual/target-os virtual/target-os-dev virtual/target-os-factory virtual/target-os-factory-shim virtual/target-os-test chromeos-base/autotest-all --sysroot /build/eve --root /build/eve --root-deps '--jobs=32' '--rebuild-exclude=chromeos-base/chromeos-chrome' '--rebuild-exclude=chromeos-base/chromium-source' '--rebuild-exclude=chromeos-base/chrome-icu'

These are the packages that would be merged, in order:

Calculating dependencies  . .... .... done in 0:01:10.579952
[binary  N     ] virtual/rust-binaries-1-r6:0/1-r6::chromiumos to /build/eve/ 16 KiB
[binary  N     ] sys-apps/baselayout-2.2-r1::chromiumos to /build/eve/ USE="kvm_host -auto_seed_etc_files" 60 KiB
[ebuild  N     ] virtual/pkgconfig-2::portage-stable to /build/eve/ 16 KiB
[binary  N     ] virtual/tmpfiles-0::portage-stable to /build/eve/ 15 KiB
[binary  N     ] dev-libs/re2-0.2021.11.01:0/9::portage-stable to /build/eve/ USE="-icu" ABI_X86="(64) -32 (-x32)" 1,364 KiB
[ebuild
'''

# First version of the regex matched this causing extraneous output.
_FOOLED_OUTPUT = '''
[58787/86177] CXX obj/content/browser/browser/push_messaging_context.o
'''


def RunSteps(api, properties):
  if properties.WhichOneof('test_oneof') == 'bad_input':
    sec_arg = properties.bad_input
  else:
    sec_arg = properties.bapi_stdout
  api.portage.publish_prebuilt_stats(properties.step_name, sec_arg)


def GenTests(api):
  yield api.test(
      'ideal',
      api.properties(
          TestMetricsInputProperties(step_name='test',
                                     bapi_stdout=_IDEAL_EMERGE_OUTPUT)),
      api.post_process(post_process.PropertyEquals, 'prebuilt_stats',
                       {'test': {
                           'binary': 6,
                           'ebuild': 2,
                       }}))

  yield api.test(
      'partial-output',
      api.properties(
          TestMetricsInputProperties(step_name='test',
                                     bapi_stdout=_PARTIAL_EMERGE_OUTPUT)),
      api.post_process(post_process.PropertyEquals, 'prebuilt_stats',
                       {'test': {
                           'binary': 4,
                           'ebuild': 1,
                       }}))

  yield api.test(
      'fooled-output',
      api.properties(
          TestMetricsInputProperties(step_name='test',
                                     bapi_stdout=_FOOLED_OUTPUT)),
      api.post_process(post_process.PropertyEquals, 'prebuilt_stats', {}))

  yield api.test(
      'empty-output',
      api.properties(
          TestMetricsInputProperties(step_name='test',
                                     bapi_stdout=_NO_EMERGE_OUTPUT)),
      api.post_process(post_process.PropertyEquals, 'prebuilt_stats', {}))
  yield api.test(
      'bad-type',
      api.properties(
          TestMetricsInputProperties(step_name='test', bad_input=_BAD_TYPE)),
      api.post_process(post_process.PropertiesDoNotContain, 'prebuilt_stats'),
      api.post_check(post_process.StatusSuccess))
