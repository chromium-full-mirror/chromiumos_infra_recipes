# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit test match_test_variants_sources API"""
from google.protobuf import json_format

from PB.go.chromium.org.luci.resultdb.proto.v1.resultdb import \
  QueryTestVariantsResponse
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/luci_analysis',
    'recipe_engine/raw_io',
    'recipe_engine/resultdb',
    'exoneration_util',
]


def RunSteps(api):
  variants = get_variants()
  # Calls resultdb
  result = api.exoneration_util.match_test_variants_sources(variants)
  api.assertions.assertEqual(len(result), 2)
  api.assertions.assertEqual(
      result[0]['sources']['gitilesCommit']['commitHash'],
      '93cf925c8cd052ebbe6133a8cef885d92c56cdc5')
  api.assertions.assertEqual(
      result[1]['sources']['gitilesCommit']['commitHash'],
      '93cf925c8cd052ebbe6133a8cef885d92c56cdc5')

  def query_func_multiple_pages(page_token=None):
    if page_token:
      return load_data(single_source)
    data = load_data(multiple_sources)
    data.next_page_token = '1'
    return data

  # Fake multiple pages: the second page has the identical variants to the first
  # page but with different sources; the second page sources are used.
  result = api.exoneration_util.match_test_variants_sources(
      variants, fake_query_func=query_func_multiple_pages)
  api.assertions.assertEqual(len(result), 2)
  api.assertions.assertEqual(
      result[0]['sources']['gitilesCommit']['commitHash'],
      '93cf925c8cd052ebbe6133a8cef885d92c56cdc5')
  api.assertions.assertEqual(
      result[1]['sources']['gitilesCommit']['commitHash'],
      '93cf925c8cd052ebbe6133a8cef885d92c56cdc5')

  # Fake multiple sources
  result = api.exoneration_util.match_test_variants_sources(
      variants, fake_query_func=lambda page_token: load_data(multiple_sources))
  api.assertions.assertEqual(len(result), 2)
  api.assertions.assertEqual(
      result[0]['sources']['gitilesCommit']['commitHash'], 'aaaa')
  api.assertions.assertEqual(
      result[1]['sources']['gitilesCommit']['commitHash'], 'bbbb')


def GenTests(api):

  yield api.test(
      'basic',
      # This mocks the response of resultdb API call.
      api.resultdb.query_test_variants(load_data(single_source)),
      api.post_process(post_process.DropExpectation),
  )


def load_data(content):
  return json_format.Parse(text=content, message=QueryTestVariantsResponse(),
                           ignore_unknown_fields=True)


def get_variants():
  return [{
      'testId': 'tast.hwsec.Login',
      'variant': {
          'def': {
              'build_target': 'amd64-generic'
          }
      }
  }, {
      'testId': 'tast.session.OwnershipTaken',
      'variant': {
          'def': {
              'build_target': 'amd64-generic'
          }
      }
  }]


single_source = '''{
    "testVariants": [
        {
            "testId": "tast.hwsec.Login",
            "variant": {
                "def": {
                    "build_target": "amd64-generic"
                }
            },
            "variantHash": "6d35426b9fce79e2",
            "status": "EXONERATED",
            "sourcesId": "a5165284865bd2dac42337e8"
        },
        {
            "testId": "tast.session.OwnershipTaken",
            "variant": {
                "def": {
                    "build_target": "amd64-generic"
                }
            },
            "variantHash": "6d35426b9fce79e2",
            "status": "EXONERATED",
            "sourcesId": "a5165284865bd2dac42337e8"
        }
    ],
    "sources": {
        "a5165284865bd2dac42337e8": {
            "gitilesCommit": {
                "host": "chrome-internal.googlesource.com",
                "project": "chromeos/manifest-internal",
                "ref": "refs/heads/snapshot",
                "commitHash": "93cf925c8cd052ebbe6133a8cef885d92c56cdc5",
                "position": "92279"
            },
            "changelists": [
                {
                    "host": "chromium-review.googlesource.com",
                    "project": "chromiumos/overlays/chromiumos-overlay",
                    "change": "5138795",
                    "patchset": "2"
                }
            ]
        }
    }
}'''

multiple_sources = '''{
    "testVariants": [
        {
            "testId": "tast.hwsec.Login",
            "variant": {
                "def": {
                    "build_target": "dedede",
                    "model": "dedede"
                }
            },
            "variantHash": "dedede",
            "status": "EXONERATED",
            "sourcesId": "a"
        },
        {
            "testId": "tast.session.OwnershipTaken",
            "variant": {
                "def": {
                    "board": "betty"
                }
            },
            "variantHash": "betty",
            "status": "EXONERATED",
            "sourcesId": "b"
        },
        {
            "testId": "tast.hwsec.Login",
            "variant": {
                "def": {
                    "build_target": "amd64-generic"
                }
            },
            "variantHash": "6d35426b9fce79e2",
            "status": "EXONERATED",
            "sourcesId": "a"
        },
        {
            "testId": "tast.session.OwnershipTaken",
            "variant": {
                "def": {
                    "build_target": "amd64-generic"
                }
            },
            "variantHash": "6d35426b9fce79e2",
            "status": "EXONERATED",
            "sourcesId": "b"
        }
    ],
    "sources": {
        "a": {
            "gitilesCommit": {
                "host": "chrome-internal.googlesource.com",
                "project": "chromeos/manifest-internal",
                "ref": "refs/heads/snapshot",
                "commitHash": "aaaa",
                "position": "92279"
            },
            "changelists": [
                {
                    "host": "chromium-review.googlesource.com",
                    "project": "chromiumos/overlays/chromiumos-overlay",
                    "change": "5138795",
                    "patchset": "2"
                }
            ]
        },
        "b": {
            "gitilesCommit": {
                "host": "chrome-internal.googlesource.com",
                "project": "chromeos/manifest-internal",
                "ref": "refs/heads/snapshot",
                "commitHash": "bbbb",
                "position": "92280"
            },
            "changelists": [
                {
                    "host": "chromium-review.googlesource.com",
                    "project": "chromiumos/overlays/chromiumos-overlay",
                    "change": "5138795",
                    "patchset": "3"
                }
            ]
        }
    }
}'''
