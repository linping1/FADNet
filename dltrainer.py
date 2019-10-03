from __future__ import print_function
import os
import time
import torch
import torch.nn.functional as F
import numpy as np
from torchvision import transforms
from torch.utils.data import DataLoader

from net_builder import build_net
#from dataset import DispDataset
from dataloader.SceneFlowLoader import DispDataset
from dataloader.SIRSLoader import SIRSDataset
from dataloader.GANet.data import get_training_set, get_test_set
from utils.AverageMeter import AverageMeter
from utils.common import logger
from losses.multiscaleloss import EPE
from utils.preprocess import scale_disp, scale_norm

class DisparityTrainer(object):
    def __init__(self, net_name, lr, devices, dataset, trainlist, vallist, datapath, batch_size, maxdisp, pretrain=None):
        super(DisparityTrainer, self).__init__()
        self.net_name = net_name
        self.lr = lr
        self.current_lr = lr
        self.devices = devices
        self.devices = [int(item) for item in devices.split(',')]
        ngpu = len(devices)
        self.ngpu = ngpu
        self.trainlist = trainlist
        self.vallist = vallist
        self.dataset = dataset
        self.datapath = datapath
        self.batch_size = batch_size
        self.pretrain = pretrain 
        self.maxdisp = maxdisp

        #self.criterion = criterion
        self.criterion = None
        self.epe = EPE
        self.initialize()

    def _prepare_dataset(self):

        if self.dataset == 'irs':
            train_dataset = SIRSDataset(txt_file = self.trainlist, root_dir = self.datapath, phase='train', load_disp = self.disp_on, load_norm = self.norm_on)
            test_dataset = SIRSDataset(txt_file = self.vallist, root_dir = self.datapath, phase='test', load_disp = self.disp_on, load_norm = self.norm_on)
        else:
            train_dataset = DispDataset(txt_file = self.trainlist, root_dir = self.datapath, phase='train')
            test_dataset = DispDataset(txt_file = self.vallist, root_dir = self.datapath, phase='test')
        
        datathread=4
        if os.environ.get('datathread') is not None:
            datathread = int(os.environ.get('datathread'))
        logger.info("Use %d processes to load data..." % datathread)
        self.train_loader = DataLoader(train_dataset, batch_size = self.batch_size, \
                                shuffle = True, num_workers = datathread, \
                                pin_memory = True)
        
        self.test_loader = DataLoader(test_dataset, batch_size = self.batch_size / 4, \
                                shuffle = False, num_workers = datathread, \
                                pin_memory = True)
        self.num_batches_per_epoch = len(self.train_loader)

        ## GANet loader
        #print('===> Loading datasets')
        #train_set = get_training_set(self.datapath, self.trainlist, [256, 576], False, False, False, 0)
        #test_set = get_test_set(self.datapath, self.vallist, [576,960], False, False, False)
        #self.train_loader = DataLoader(train_set, batch_size = self.batch_size, \
        #                        shuffle = True, num_workers = 16, \
        #                        pin_memory = True)
        #
        #self.test_loader = DataLoader(test_set, batch_size = self.batch_size / 2, \
        #                        shuffle = False, num_workers = 4, \
        #                        pin_memory = True)
        #self.num_batches_per_epoch = len(self.train_loader)


    def _build_net(self):

        # build net according to the net name
        if self.net_name == "psmnet" or self.net_name == "ganet":
            self.net = build_net(self.net_name)(self.maxdisp)
        else:
            self.net = build_net(self.net_name)(batchNorm=False, lastRelu=True, maxdisp=self.maxdisp)

        # set predicted target
        if self.net_name == "dispnormnet":
            self.disp_on = True
            self.norm_on = True
        else:
            self.disp_on = True
            self.norm_on = False

        self.is_pretrain = False

        if self.ngpu > 1:
            self.net = torch.nn.DataParallel(self.net, device_ids=self.devices).cuda()
        else:
            self.net.cuda()

        if self.pretrain == '':
            logger.info('Initial a new model...')
        else:
            if os.path.isfile(self.pretrain):
                model_data = torch.load(self.pretrain)
                logger.info('Load pretrain model: %s', self.pretrain)
                if 'state_dict' in model_data.keys():
                    self.net.load_state_dict(model_data['state_dict'])
                else:
                    self.net.load_state_dict(model_data)
                self.is_pretrain = True
            else:
                logger.warning('Can not find the specific model %s, initial a new model...', self.pretrain)


    def _build_optimizer(self):
        beta = 0.999
        momentum = 0.9
        self.optimizer = torch.optim.Adam(self.net.parameters(), self.lr,
                                        betas=(momentum, beta), amsgrad=True)

    def initialize(self):
        self._build_net()
        self._prepare_dataset()
        self._build_optimizer()

    def adjust_learning_rate(self, epoch):
        #if epoch < 10:
        #    cur_lr = 0.001
        #elif epoch < 20:
        #    cur_lr = 0.0001
        #else:
        #    cur_lr = 0.0001 / (2**((epoch - 20)// 10))
        cur_lr = self.lr / (2**(epoch// 10))
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = cur_lr
        self.current_lr = cur_lr
        return cur_lr

    def set_criterion(self, criterion):
        self.criterion = criterion
 
    def train_one_epoch(self, epoch):
        batch_time = AverageMeter()
        data_time = AverageMeter()
        losses = AverageMeter()
        flow2_EPEs = AverageMeter()
        norm_EPEs = AverageMeter()
        # switch to train mode
        self.net.train()
        end = time.time()
        cur_lr = self.adjust_learning_rate(epoch)
        logger.info("learning rate of epoch %d: %f." % (epoch, cur_lr))
        for i_batch, sample_batched in enumerate(self.train_loader):
         
            left_input = torch.autograd.Variable(sample_batched['img_left'].cuda(), requires_grad=False)
            right_input = torch.autograd.Variable(sample_batched['img_right'].cuda(), requires_grad=False)
            input = torch.cat((left_input, right_input), 1)

            if self.disp_on:
                target_disp = sample_batched['gt_disp']
                target_disp = target_disp.cuda()
                target_disp = torch.autograd.Variable(target_disp, requires_grad=False)
            if self.norm_on:
                target_norm = sample_batched['gt_norm']
                target_norm = target_norm.cuda()
                target_norm = torch.autograd.Variable(target_norm, requires_grad=False)

            input_var = torch.autograd.Variable(input, requires_grad=False)
            data_time.update(time.time() - end)

            self.optimizer.zero_grad()
            if self.net_name == "dispnormnet":
                disp_norm = self.net(input_var)
                disps = disp_norm[0]
                normal = disp_norm[1]
                loss_disp = self.criterion(disps, target_disp)
                loss_norm = F.mse_loss(normal, target_norm, size_average=True) * 3.0
                loss = loss_disp + loss_norm
                final_disp = disps[0]
                flow2_EPE = self.epe(final_disp, target_disp)
                norm_EPE = loss_norm 
            elif self.net_name == "dispnetcres":
                output_net1, output_net2 = self.net(input_var)
                loss_net1 = self.criterion(output_net1, target_disp)
                loss_net2 = self.criterion(output_net2, target_disp)
                loss = loss_net1 + loss_net2
                output_net2_final = output_net2[0]
                flow2_EPE = self.epe(output_net2_final, target_disp)
            elif self.net_name == "dispnetcs":
                output_net1, output_net2 = self.net(input_var)
                loss_net1 = self.criterion(output_net1, target_disp)
                loss_net2 = self.criterion(output_net2, target_disp)
                loss = loss_net1 + loss_net2
                output_net2_final = output_net2[0]
                flow2_EPE = self.epe(output_net2_final, target_disp)
            elif self.net_name == "dispnetcss":
                output_net1, output_net2, output_net3 = self.net(input_var)
                loss_net1 = self.criterion(output_net1, target_disp)
                loss_net2 = self.criterion(output_net2, target_disp)
                loss_net3 = self.criterion(output_net3, target_disp)
                loss = loss_net1 + loss_net2 + loss_net3
                output_net3_final = output_net3[0]
                flow2_EPE = self.epe(output_net3_final, target_disp)
            elif self.net_name == "psmnet" or self.net_name == "ganet":
                mask = target_disp < self.maxdisp
                mask.detach_()

                output1, output2, output3 = self.net(input_var)
                output1 = torch.unsqueeze(output1,1)
                output2 = torch.unsqueeze(output2,1)
                output3 = torch.unsqueeze(output3,1)

                loss = 0.5*F.smooth_l1_loss(output1[mask], target_disp[mask], size_average=True) + 0.7*F.smooth_l1_loss(output2[mask], target_disp[mask], size_average=True) + F.smooth_l1_loss(output3[mask], target_disp[mask], size_average=True)
                flow2_EPE = self.epe(output3, target_disp)
            else:
                output = self.net(input_var)
                loss = self.criterion(output, target_disp)
                if type(loss) is list or type(loss) is tuple:
                    loss = np.sum(loss)
                if type(output) is list or type(output) is tuple:
                    flow2_EPE = self.epe(output[0], target_disp)
                else:
                    flow2_EPE = self.epe(output, target_disp)

            # record loss and EPE
            losses.update(loss.data.item(), target_disp.size(0))
            if self.disp_on:
                flow2_EPEs.update(flow2_EPE.data.item(), target_disp.size(0))
            if self.norm_on:
                norm_EPEs.update(norm_EPE.data.item(), target_disp.size(0))

            # compute gradient and do SGD step
            loss.backward()
            self.optimizer.step()

            # measure elapsed time
            batch_time.update(time.time() - end)
            end = time.time()

            if i_batch % 10 == 0:
                logger.info('Epoch: [{0}][{1}/{2}]\t'
                  'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                  'Loss {loss.val:.3f} ({loss.avg:.3f})\t'
                  'EPE {flow2_EPE.val:.3f} ({flow2_EPE.avg:.3f})\t'
                  'norm_EPE {norm_EPE.val:.3f} ({norm_EPE.avg:.3f})'.format(
                  epoch, i_batch, self.num_batches_per_epoch, batch_time=batch_time, 
                  data_time=data_time, loss=losses, flow2_EPE=flow2_EPEs, norm_EPE=norm_EPEs))

            #if i_batch > 10:
            #    break

        return losses.avg, flow2_EPEs.avg

    def validate(self):
        batch_time = AverageMeter()
        flow2_EPEs = AverageMeter()
        norm_EPEs = AverageMeter()
        losses = AverageMeter()
        # switch to evaluate mode
        self.net.eval()
        end = time.time()
        #scale_width = 960
        #scale_height = 540
        #scale_width = 3130
        #scale_height = 960
        for i, sample_batched in enumerate(self.test_loader):

            left_input = torch.autograd.Variable(sample_batched['img_left'].cuda(), requires_grad=False)
            right_input = torch.autograd.Variable(sample_batched['img_right'].cuda(), requires_grad=False)
            #left_input = torch.autograd.Variable(sample_batched[0].cuda(), requires_grad=False)
            #right_input = torch.autograd.Variable(sample_batched[1].cuda(), requires_grad=False)
            #target = sample_batched[2]

            input = torch.cat((left_input, right_input), 1)
            input_var = torch.autograd.Variable(input, requires_grad=False)

            if self.disp_on:
                target_disp = sample_batched['gt_disp']
                target_disp = target_disp.cuda()
                target_disp = torch.autograd.Variable(target_disp, requires_grad=False)
            if self.norm_on:
                target_norm = sample_batched['gt_norm']
                target_norm = target_norm.cuda()
                target_norm = torch.autograd.Variable(target_norm, requires_grad=False)

            if self.net_name == 'dispnormnet':
                disp, normal = self.net(input_var)
                size = disp.size()

                # scale the result
                disp_norm = torch.cat((normal, disp), 1)
                disp_norm = scale_norm(disp_norm, (size[0], 4, 540, 960), True)
                disp = disp_norm[:, 3, :, :].unsqueeze(1)
                normal = disp_norm[:, :3, :, :]

                #norm_EPE = self.epe(normal, target_disp[:, :3, :, :]) 
                norm_EPE = F.mse_loss(normal, target_norm, size_average=True) * 3.0
                flow2_EPE = self.epe(disp, target_disp)
            if self.net_name == 'dispnetcres':
                output_net1, output_net2 = self.net(input_var)
                output_net1 = scale_disp(output_net1, (output_net1.size()[0], 540, 960))
                output_net2 = scale_disp(output_net2, (output_net2.size()[0], 540, 960))

                loss_net1 = self.epe(output_net1, target_disp)
                loss_net2 = self.epe(output_net2, target_disp)
                loss = loss_net1 + loss_net2
                flow2_EPE = self.epe(output_net2, target_disp)
            elif self.net_name == "psmnet" or self.net_name == "ganet":
                output_net3 = self.net(input_var)
                output_net3 = scale_disp(output_net3, (output_net3.size()[0], 540, 960))
                loss = self.epe(output_net3, target_disp)
                flow2_EPE = loss
            elif self.net_name == 'dispnetcss':
                output_net1, output_net2, output_net3 = self.net(input_var)
                output_net1 = scale_disp(output_net1, (output_net1.size()[0], 540, 960))
                output_net2 = scale_disp(output_net2, (output_net2.size()[0], 540, 960))
                output_net3 = scale_disp(output_net3, (output_net3.size()[0], 540, 960))

                loss_net1 = self.epe(output_net1, target_disp)
                loss_net2 = self.epe(output_net2, target_disp)
                loss_net3 = self.epe(output_net3, target_disp)
                loss = loss_net1 + loss_net2 + loss_net3
                flow2_EPE = self.epe(output_net3, target_disp)
            else:
                output = self.net(input_var)
                output_net1 = output[0]
                #output_net1 = output_net1.squeeze(1)
                #print(output_net1.size())
                output_net1 = scale_disp(output_net1, (output_net1.size()[0], 540, 960))
                #output_net1 = torch.from_numpy(output_net1).unsqueeze(1).cuda()
                loss = self.epe(output_net1, target_disp)
                flow2_EPE = self.epe(output_net1, target_disp)

                #if type(loss) is list or type(loss) is tuple:
                #    loss = loss[0]
                #if type(output) is list or type(output_net1) :
                #    flow2_EPE = self.epe(output[0], target_disp)
                #else:
                #    flow2_EPE = self.epe(output, target_disp)

            # record loss and EPE
            if loss.data.item() == loss.data.item():
                losses.update(loss.data.item(), target_disp.size(0))
            if self.disp_on and (flow2_EPE.data.item() == flow2_EPE.data.item()):
                flow2_EPEs.update(flow2_EPE.data.item(), target_disp.size(0))
            if self.norm_on and (norm_EPE.data.item() == norm_EPE.item()):
                norm_EPEs.update(norm_EPE.data.item(), target_disp.size(0))
        
            # measure elapsed time
            batch_time.update(time.time() - end)
            end = time.time()
    
            if i % 10 == 0:
                logger.info('Test: [{0}/{1}]\t Time {2}\t EPE {3}\t norm_EPE {4}'
                      .format(i, len(self.test_loader), batch_time.val, flow2_EPEs.val, norm_EPEs.val))

            #if i % 10 == 0:
            #    break

        logger.info(' * EPE {:.3f}'.format(flow2_EPEs.avg))
        logger.info(' * normal EPE {:.3f}'.format(norm_EPEs.avg))
        return flow2_EPEs.avg

    def get_model(self):
        return self.net.state_dict()


