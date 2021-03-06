#!/usr/bin/env python3
# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the LICENSE file in
# the root directory of this source tree. An additional grant of patent rights
# can be found in the PATENTS file in the same directory.
#

import argparse
from itertools import zip_longest
import os
import shutil

from fairseq import dictionary, indexed_dataset
from fairseq.tokenizer import Tokenizer


def main():
    parser = argparse.ArgumentParser(
        description='Data pre-processing: Create dictionary and store data in binary format')
    parser.add_argument('-s', '--source-lang', default=None, metavar='SRC', help='source language')
    parser.add_argument('-t', '--target-lang', default=None, metavar='TARGET', help='target language')
    parser.add_argument('--trainpref', metavar='FP', default='train', help='target language')
    parser.add_argument('--validpref', metavar='FP', default='valid', help='comma separated, valid language prefixes')
    parser.add_argument('--testpref', metavar='FP', default='test', help='comma separated, test language prefixes')
    parser.add_argument('--destdir', metavar='DIR', default='data-bin', help='destination dir')
    # 如果训练集很大, 那么会产生很多低频词, 这些词没有意义很大可能是拼写错误
    # 那么可以通过下面两个参数过滤的低频词, 如果值为10, 则过滤掉频率小于10的词, 这些词不会出现在dict.txt文件中
    parser.add_argument('--thresholdtgt', metavar='N', default=0, type=int,
                        help='map words appearing less than threshold times to unknown')
    parser.add_argument('--thresholdsrc', metavar='N', default=0, type=int,
                        help='map words appearing less than threshold times to unknown')
    # 如果自己已经有准备好的字典, 可以通过下面两个参数设置
    parser.add_argument('--tgtdict', metavar='FP', help='reuse given target dictionary')
    parser.add_argument('--srcdict', metavar='FP', help='reuse given source dictionary')
    # 限制用于训练的单词数
    parser.add_argument('--nwordstgt', metavar='N', default=-1, type=int, help='number of target words to retain')
    parser.add_argument('--nwordssrc', metavar='N', default=-1, type=int, help='number of source words to retain')
    # 对齐文件格式（train文件）: 原文词id-译文词id 多个使用空格分开， 一行代表一句话（eg：0-0 1-2 1-3 2-1 3-4 5-6 7-7）
    # 对齐文件可以是其他工具生成的对齐文件或者人工对齐的文件
    # https://github.com/facebookresearch/fairseq-py/blob/master/preprocess.py#L99
    # 注意： 对齐文件的行数必须跟train.en文件的行数一样， 而不是跟数据集总行数一样
    parser.add_argument('--alignfile', metavar='ALIGN', default=None, help='an alignment file (optional)')
    parser.add_argument('--output-format', metavar='FORMAT', default='binary', choices=['binary', 'raw'],
                        help='output format (optional)')

    args = parser.parse_args()
    print(args)
    os.makedirs(args.destdir, exist_ok=True)

    if args.srcdict:
        src_dict = dictionary.Dictionary.load(args.srcdict)
    else:
        src_dict = Tokenizer.build_dictionary(filename='{}.{}'.format(args.trainpref, args.source_lang))
    src_dict.save(os.path.join(args.destdir, 'dict.{}.txt'.format(args.source_lang)),
                  threshold=args.thresholdsrc, nwords=args.nwordssrc)

    if args.tgtdict:
        tgt_dict = dictionary.Dictionary.load(args.tgtdict)
    else:
        tgt_dict = Tokenizer.build_dictionary(filename='{}.{}'.format(args.trainpref, args.target_lang))
    tgt_dict.save(os.path.join(args.destdir, 'dict.{}.txt'.format(args.target_lang)),
                  threshold=args.thresholdtgt, nwords=args.nwordstgt)

    def make_binary_dataset(input_prefix, output_prefix, lang):
        dict = dictionary.Dictionary.load(os.path.join(args.destdir, 'dict.{}.txt'.format(lang)))
        print('| [{}] Dictionary: {} types'.format(lang, len(dict) - 1))

        ds = indexed_dataset.IndexedDatasetBuilder(
            '{}/{}.{}-{}.{}.bin'.format(args.destdir, output_prefix, args.source_lang,
                                        args.target_lang, lang)
        )

        def consumer(tensor):
            ds.add_item(tensor)

        input_file = '{}.{}'.format(input_prefix, lang)
        res = Tokenizer.binarize(input_file, dict, consumer)
        print('| [{}] {}: {} sents, {} tokens, {:.3}% replaced by {}'.format(
            lang, input_file, res['nseq'], res['ntok'],
            100 * res['nunk'] / res['ntok'], dict.unk_word))
        ds.finalize('{}/{}.{}-{}.{}.idx'.format(
            args.destdir, output_prefix,
            args.source_lang, args.target_lang, lang))

    def make_dataset(input_prefix, output_prefix, lang, output_format='binary'):
        if output_format == 'binary':
            make_binary_dataset(input_prefix, output_prefix, lang)
        elif output_format == 'raw':
            # Copy original text file to destination folder
            output_text_file = os.path.join(args.destdir, '{}.{}'.format(output_prefix, lang))
            shutil.copyfile('{}.{}'.format(input_prefix, lang), output_text_file)

    make_dataset(args.trainpref, 'train', args.source_lang, args.output_format)
    make_dataset(args.trainpref, 'train', args.target_lang, args.output_format)
    for k, validpref in enumerate(args.validpref.split(',')):
        outprefix = 'valid{}'.format(k) if k > 0 else 'valid'
        make_dataset(validpref, outprefix, args.source_lang, args.output_format)
        make_dataset(validpref, outprefix, args.target_lang, args.output_format)
    for k, testpref in enumerate(args.testpref.split(',')):
        outprefix = 'test{}'.format(k) if k > 0 else 'test'
        make_dataset(testpref, outprefix, args.source_lang, args.output_format)
        make_dataset(testpref, outprefix, args.target_lang, args.output_format)
    print('| Wrote preprocessed data to {}'.format(args.destdir))

    if args.alignfile:
        src_file_name = '{}.{}'.format(args.trainpref, args.source_lang)
        tgt_file_name = '{}.{}'.format(args.trainpref, args.target_lang)
        src_dict = dictionary.Dictionary.load(os.path.join(args.destdir, 'dict.{}.txt'.format(args.source_lang)))
        tgt_dict = dictionary.Dictionary.load(os.path.join(args.destdir, 'dict.{}.txt'.format(args.target_lang)))
        freq_map = {}
        with open(args.alignfile, 'r') as align_file:
            with open(src_file_name, 'r') as src_file:
                with open(tgt_file_name, 'r') as tgt_file:
                    for a, s, t in zip_longest(align_file, src_file, tgt_file):
                        si = Tokenizer.tokenize(s, src_dict, add_if_not_exist=False)
                        ti = Tokenizer.tokenize(t, tgt_dict, add_if_not_exist=False)
                        ai = list(map(lambda x: tuple(x.split('-')), a.split()))
                        for sai, tai in ai:
                            srcidx = si[int(sai)]
                            tgtidx = ti[int(tai)]
                            if srcidx != src_dict.unk() and tgtidx != tgt_dict.unk():
                                assert srcidx != src_dict.pad()
                                assert srcidx != src_dict.eos()
                                assert tgtidx != tgt_dict.pad()
                                assert tgtidx != tgt_dict.eos()

                                if srcidx not in freq_map:
                                    freq_map[srcidx] = {}
                                if tgtidx not in freq_map[srcidx]:
                                    freq_map[srcidx][tgtidx] = 1
                                else:
                                    freq_map[srcidx][tgtidx] += 1

        align_dict = {}
        for srcidx in freq_map.keys():
            align_dict[srcidx] = max(freq_map[srcidx], key=freq_map[srcidx].get)

        with open(os.path.join(args.destdir, 'alignment.{}-{}.txt'.format(
                args.source_lang, args.target_lang)), 'w') as f:
            for k, v in align_dict.items():
                print('{} {}'.format(src_dict[k], tgt_dict[v]), file=f)


if __name__ == '__main__':
    main()
