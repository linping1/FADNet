python main.py --cuda --outf ./models/girl-ir-dispCSRes --lr 0.01 --logFile girl-ir-train-dispCSRes.log --showFreq 1 --devices 0,1,2,3 --trainlist ./lists/exclude_1536_TRAIN.list  --vallist ./lists/exclude_1536_TEST.list --startEpoch 0 --datapath /home/vradmin/data/virtual3 --batchSize 8 --endEpoch 200 --domain_transfer 0

