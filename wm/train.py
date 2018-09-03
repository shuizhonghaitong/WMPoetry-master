from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import math
import os
import random
import time

import numpy as np
from six.moves import xrange  # pylint: disable=redefined-builtin
import tensorflow as tf

from model import PoemModel
from tool import PoetryTool
from config import hps

class PoemTrainer(object):

    def __init__(self):
        # Construct hyper-parameter
        self.hps = hps
        self.tool = PoetryTool(sens_num=hps.sens_num,
            key_slots=hps.key_slots, enc_len=hps.bucket[0],
            dec_len=hps.bucket[1])
        # If there isn't a pre-trained word embedding, just
        # set it to None, then the word embedding
        # will be initialized with a norm distribution.
        if hps.init_emb == '':
            self.init_emb = None
        else:
            self.init_emb = np.load(self.hps.init_emb)
            print ("init_emb_size: %s" % str(np.shape(self.init_emb)))
        self.tool.load_dic(hps.vocab_path, hps.ivocab_path)

        vocab_size = self.tool.get_vocab_size()
        assert vocab_size > 0
        PAD_ID = self.tool.get_PAD_ID()
        print (PAD_ID)
        assert PAD_ID > 0

        self.hps = self.hps._replace(vocab_size=vocab_size, PAD_ID=PAD_ID)

        print("Params  sets: ")
        print (self.hps)
        print("___________________")
        raw_input("Please check the parameters and press enter to continue>")


    def create_model(self, session, model):
        """Create the model and initialize or load parameters in session."""
        ckpt = tf.train.get_checkpoint_state(self.hps.model_path)
        if ckpt and tf.gfile.Exists(ckpt.model_checkpoint_path):
            print("Reading model parameters from %s" %
                  ckpt.model_checkpoint_path)
            model.saver.restore(session, ckpt.model_checkpoint_path)
        else:
            print("Created model with fresh parameters.")
            session.run(tf.global_variables_initializer())

        return model

    def sample(self, enc_inps, dec_inps, key_inps, outputs):

        sample_num = self.hps.sample_num
        if sample_num > self.hps.batch_size:
            sample_num = self.hps.batch_size

        # Random select some examples
        idxes = random.sample(range(0, self.hps.batch_size), 
            sample_num)

        #
        for idx in idxes:
            keys = []
            for i in xrange (0, self.hps.key_slots):
                key_idx = [key_inps[i][0][idx], key_inps[i][1][idx]]
                keys.append("".join(self.tool.idxes2chars(key_idx)))
            key_str = " ".join(keys)

            # Build lines
            print ("%s" % (key_str))
            for step in xrange(0, self.hps.sens_num):
                inputs = [c[idx] for c in enc_inps[step]]
                sline = "".join(self.tool.idxes2chars(inputs))

                target = [c[idx] for c in dec_inps[step]]
                tline = "".join(self.tool.idxes2chars(target))

                outline = [c[idx] for c in outputs[step]] #长度为dec_len的list，每个元素是长度为vocab_size的list
                outline = self.tool.greedy_search(outline)

                if step == 0:
                    print(sline.ljust(25) + " # " + tline.ljust(30) + " # " + outline.ljust(30) + " # ")
                else:
                    print(sline.ljust(30) + " # " + tline.ljust(30) + " # " + outline.ljust(30) + " # ")


    def run_validation(self, sess, model, valid_batches, valid_batch_num, epoch):
        print("run validation...")
        total_gen_loss = 0.0
        total_l2_loss = 0.0
        for step in xrange(0, valid_batch_num):
            batch = valid_batches[step]
            outputs, gen_loss, l2_loss = model.step(sess, batch, True) #返回的应该是2个？ 没有l2_loss
            total_gen_loss += gen_loss
            total_l2_loss += l2_loss
        total_gen_loss /= valid_batch_num
        total_l2_loss /= valid_batch_num
        info = "validation epoch: %d  loss: %.3f  ppl: %.2f  l2 loss: %.4f" % \
            (epoch, total_gen_loss, np.exp(total_gen_loss), total_l2_loss)
        print (info)
        fout = open("validlog.txt", 'a')
        fout.write(info + "\n")
        fout.close()

    def train(self):
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.98)
        gpu_options.allow_growth = True

        with tf.Session(config=tf.ConfigProto(gpu_options=gpu_options)) as sess:

            # Create model.
            model = PoemModel(self.hps, self.init_emb)
            self.create_model(sess, model)

            # Build batched data
            train_batch_num, valid_batch_num, \
            train_batches, valid_batches = self.tool.build_data(
                self.hps.batch_size, self.hps.train_data, self.hps.valid_data)

            print ("train_batch_num: %d" % (train_batch_num))
            print ("valid_batch_num: %d" % (valid_batch_num))

            for epoch in xrange(1, self.hps.max_epoch+1):
                total_gen_loss = 0.0
                time1 = time.time()

                for step in xrange(0, train_batch_num):
                    batch = train_batches[step]
                    outputs, gen_loss = model.step(sess, batch, False)
                    total_gen_loss += gen_loss

                    if step % self.hps.steps_per_train_log == 0:
                        time2 = time.time()
                        time_cost = float(time2-time1) / self.hps.steps_per_train_log
                        time1 = time2
                        process_info = "epoch: %d, %d/%d %.3f%%, %.3f s per iter" % (epoch, step, train_batch_num,
                            float(step+1) /train_batch_num * 100, time_cost)
                        

                        self.sample(batch['enc_inps'], batch['dec_inps'], batch['key_inps'], outputs)
                        current_gen_loss = total_gen_loss / (step+1)
                        ppl = math.exp(current_gen_loss) if current_gen_loss < 300 else float('inf')
                        train_info = "train loss: %.3f  ppl:%.2f" % (current_gen_loss, ppl)
                        print (process_info)
                        print(train_info)
                        print("______________________")
                        
                        info = process_info + " " + train_info
                        fout = open("trainlog.txt", 'a')
                        fout.write(info + "\n")
                        fout.close()


                current_epoch = int(model.global_step.eval() // train_batch_num) # //表示整数除法，返回不大于结果的一个最大的整数

                
                if epoch > self.hps.burn_down:
                    lr0 = model.learning_rate.eval()
                    print ("lr decay...")
                    sess.run(model.learning_rate_decay_op)
                    lr1 = model.learning_rate.eval()
                    print ("%.4f to %.4f" % (lr0, lr1))

                if epoch % self.hps.epoches_per_validate == 0:
                    self.run_validation(sess, model, valid_batches, valid_batch_num, epoch)

                if epoch % self.hps.epoches_per_checkpoint == 0:
                    # Save checkpoint and zero timer and loss.
                    print ("saving model...")
                    checkpoint_path = os.path.join(self.hps.model_path, "poem.ckpt" + "_" + str(current_epoch))
                    model.saver.save(sess, checkpoint_path, global_step=model.global_step)
                
                print("shuffle data...")
                random.shuffle(train_batches)

def main(_):
    trainer = PoemTrainer()
    trainer.train()

if __name__ == "__main__":
    tf.app.run()
