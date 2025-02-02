from torch.utils.data import Dataset
import re
from kobert.pytorch_kobert import get_pytorch_kobert_model
from kobert.utils import get_tokenizer
import numpy as np
import gluonnlp as nlp
from torch import nn
import torch
import os
device = torch.device("cpu")
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# In[4]:


class BERTClassifier(nn.Module):
    def __init__(self,
                 bert,
                 hidden_size=768,
                 num_classes=7,
                 dr_rate=None,
                 params=None):
        super(BERTClassifier, self).__init__()
        self.bert = bert
        self.dr_rate = dr_rate

        self.classifier = nn.Linear(hidden_size, num_classes)
        if dr_rate:
            self.dropout = nn.Dropout(p=dr_rate)

    def gen_attention_mask(self, token_ids, valid_length):
        attention_mask = torch.zeros_like(token_ids)
        for i, v in enumerate(valid_length):
            attention_mask[i][:v] = 1
        return attention_mask.float()

    def forward(self, token_ids, valid_length, segment_ids):
        attention_mask = self.gen_attention_mask(token_ids, valid_length)

        _, pooler = self.bert(input_ids=token_ids, token_type_ids=torch.zeros_like(
            segment_ids).long(), attention_mask=attention_mask.float().to(token_ids.device))

        if self.dr_rate:
            out = self.dropout(pooler)
        else:
            out = pooler

        return self.classifier(out)


# In[5]:


class KoBERTPredictor:
    def __init__(self, model_path="blog/model/best-epoch-36-f1-0.732.bin"):

        tokenizer = get_tokenizer()
        bertmodel, vocab = get_pytorch_kobert_model()
        self.tok = nlp.data.BERTSPTokenizer(tokenizer, vocab, lower=False)
        self.model = BERTClassifier(bertmodel)

        # load model
        model_dict = self.model.state_dict()
        checkpoint = torch.load(model_path, map_location=torch.device('cpu'))
        convert_keys = {}
        for k, v in checkpoint['model_state_dict'].items():
            new_key_name = k.replace("module.", '')
            if new_key_name not in model_dict:
                print("{} is not int model_dict".format(new_key_name))
                continue
            convert_keys[new_key_name] = v

        self.model.load_state_dict(convert_keys)

        self.model.eval()
        self.model.to(device)

    def predict(self, user_name, conversation_path):
        # 대화 리스트 들어갈 곳
        all_conversation_arr = []

        # 요일 없애야하는것
        remove_characters = "년월일-월화수목금토요 "
        cur_time = ""
        conversation = ""
        # 여기다가 원하는 카카오 데이터 셋(txt) 집어 넣으면 됨 ( 여기서는 KakaoTalk_20210426_2042_40_926_김준홍.txt 를 넣었음)
        f = open(conversation_path, 'r', encoding='UTF8')
        while True:
            line = f.readline()
            if not line:  # 마지막에 도달했을 때 반복문 빠져나옴
                break
            # 요일이 시작되는 경우
            if line[:5] == "-----":
                line = ''.join(x for x in line if x not in remove_characters)
                cur_time = line  # 년, 월, 일 형태로 받는다.(ex 2020120)
                while True:
                    line = f.readline()
                    # line 이 빈 값일 때 or 끝났을 때
                    if line[:5] == "-----" or not line:
                        break
                    # 사용자의 이름인 것만 받아온다. (한줄이 50정도max -> 한줄만 받자)
                    if line[1:len(user_name) + 1] == user_name:
                        conversation = line[16:]
                        all_conversation_arr.append(
                            [user_name, cur_time, conversation])

        for i in range(len(all_conversation_arr)):
            all_conversation_arr[i][1] = re.sub(
                "\n", "", all_conversation_arr[i][1])
            all_conversation_arr[i][2] = re.sub(
                "\n", "", all_conversation_arr[i][2])

        # 이상한 문자 있는 문장  지워버림 - 훨씬 깔끔하게 나옴
        remove_letters = "0123456789ㅂㅈㄷㄱㅅㅕㅑㅐㅔ[ㅁㄴㅇㅃㅉㄸㄲㅆㄹㅎ,_ㅗㅓㅏ※ㅣ;]'ㅋㅌㅊ)=(ㅠㅜㅍㅡabcdefghijklmnopqrstuvwxyz/QWERTYUIOPASDFGHJKLZXCVBNM#%-\":"
        for i in reversed(range(len(all_conversation_arr))):
            for x in all_conversation_arr[i][2]:
                if x in remove_letters:
                    del all_conversation_arr[i]
                    break

        # 길이가 2 이하인 문자열 제거
        for i in reversed(range(len(all_conversation_arr))):
            if len(all_conversation_arr[i][2]) <= 10 or len(all_conversation_arr[i][2]) > 56:
                del all_conversation_arr[i]

        all_conversation_arr.reverse()

        f.close()
        emo_dict = {0: 'fear', 1: 'angry', 2: 'sad', 3: 'happy', 4: 'fear'}
        result = np.zeros((1, 7), dtype=float)
        #20개만
        for i in all_conversation_arr[:20]:
            _sentence = str(i[2])
            if _sentence == '-1':
                break
            transform = nlp.data.BERTSentenceTransform(
                self.tok, max_seq_length=64, pad=True, pair=False)
            sentence = [transform([_sentence])]
            dataloader = torch.utils.data.DataLoader(sentence, batch_size=1)
            _token_ids = dataloader._index_sampler.sampler.data_source

            _t = torch.from_numpy(_token_ids[0][0])
            _t = _t.tolist()
            token_ids = torch.tensor(_t, dtype=torch.long).unsqueeze(0)
            val_len = torch.tensor([len(token_ids[0])],
                                   dtype=torch.long)

            _s = torch.from_numpy(_token_ids[0][1])
            _s = _s.tolist()
            segment_ids = torch.tensor(
                _s, dtype=torch.long).unsqueeze(0)

            out = self.model(token_ids, val_len, segment_ids)
            out_idx = np.argmax(out.cpu().detach().numpy())
            softmax = nn.Softmax(dim=1)
            score = softmax(out).cpu().detach().numpy()
            result += score
        #print(emo_dict[np.delete(result, [1, 4]).argmax()])

        return [emo_dict[np.delete(result, [1, 4]).argsort()[-1]],emo_dict[np.delete(result, [1, 4]).argsort()[-2]]]
