import asyncio
import random
from tcputils import *
import time


class Servidor:
    def __init__(self, rede, porta):
        self.rede = rede
        self.porta = porta
        self.conexoes = {}
        self.callback = None
        self.rede.registrar_recebedor(self._rdt_rcv)

    def registrar_monitor_de_conexoes_aceitas(self, callback):
        """
        Usado pela camada de aplicação para registrar uma função para ser chamada
        sempre que uma nova conexão for aceita
        """
        self.callback = callback

    def _rdt_rcv(self, src_addr, dst_addr, segment):
        src_port, dst_port, seq_no, ack_no, \
            flags, window_size, checksum, urg_ptr = read_header(segment)

        print("\033[96m {}\033[00m" .format("Chamada a _rdt_rcv de Servidor"))

        if dst_port != self.porta:
            # Ignora segmentos que não são destinados à porta do nosso servidor
            return
        if not self.rede.ignore_checksum and calc_checksum(segment, src_addr, dst_addr) != 0:
            print('descartando segmento com checksum incorreto')
            return

        payload = segment[4*(flags>>12):]
        id_conexao = (src_addr, src_port, dst_addr, dst_port)

        if (flags & FLAGS_SYN) == FLAGS_SYN:
            # A flag SYN estar setada significa que é um cliente tentando estabelecer uma conexão nova
            # TODO: talvez você precise passar mais coisas para o construtor de conexão
            
            conexao = self.conexoes[id_conexao] = Conexao(self, id_conexao)

            conexao.ack_no = new_ack_no = seq_no + 1
            conexao.seq_no = new_seq_no = random.randint(0, 0xffff)
            conexao.flags = new_flags = FLAGS_SYN | FLAGS_ACK

            header = make_header(dst_port, src_port, new_seq_no, new_ack_no, new_flags)
            new_segment = fix_checksum(header, dst_addr, src_addr)

            self.rede.enviar(new_segment, src_addr)

            # TODO: você precisa fazer o handshake aceitando a conexão. Escolha se você acha melhor
            # fazer aqui mesmo ou dentro da classe Conexao.
            if self.callback:
                self.callback(conexao)
        elif id_conexao in self.conexoes:
            # Passa para a conexão adequada se ela já estiver estabelecida
            
            self.conexoes[id_conexao]._rdt_rcv(seq_no, ack_no, flags, payload)
        else:
            print('%s:%d -> %s:%d (pacote associado a conexão desconhecida)' %
                  (src_addr, src_port, dst_addr, dst_port))


class Conexao:
    def __init__(self, servidor, id_conexao):
        self.servidor = servidor
        self.id_conexao = id_conexao # (client_addr, client_port, server_addr, server_port)
        self.callback = None
        # self.timer = asyncio.get_event_loop().call_later(1, self._exemplo_timer)  # um timer pode ser criado assim; esta linha é só um exemplo e pode ser removida
        #self.timer.cancel()   # é possível cancelar o timer chamando esse método; esta linha é só um exemplo e pode ser removida
        
        self.ack_no = None
        self.seq_no = None
        self.flags = None

        self.not_acked_segments = []
        self.timer = None
        self.timer_on = False
        self.TimeoutInterval = 1

        self.SampleRTT = None
        self.EstimatedRTT = None
        self.DevRTT = None
        # self.TimeoutInterval = None
        self.alpha = 0.125
        self.beta = 0.25
        # self.alpha = 0.25
        # self.beta = 0.5

        self.cwnd = 1
        self.window_occupation = 0
        self.remaining_data = bytearray()
        self.count_seg = 0
        self.recv_acks = 0

    # def _exemplo_timer(self):
    #     # Esta função é só um exemplo e pode ser removida
    #     print('Este é um exemplo de como fazer um timer')

    def _rdt_rcv(self, seq_no, ack_no, flags, payload):
        # TODO: trate aqui o recebimento de segmentos provenientes da camada de rede.
        # Chame self.callback(self, dados) para passar dados para a camada de aplicação após
        # garantir que eles não sejam duplicados e que tenham sido recebidos em ordem.

        # print('recebido payload: %r' % payload)
        # print("\033[91m {}\033[00m\n" .format(payload))

        # print("rcv")
        # print(f"-> ack_no = {ack_no}, seq_no = {seq_no}\n")

        # print("self")
        # print(f"-> ack_no = {self.ack_no}, seq_no = {self.seq_no}\n")

        time_recv_ack = time.time()

        # print("\033[96m {}\033[00m" .format(f"Início da função em {time.time()}"))

        if not (seq_no == self.ack_no):
            print("\033[91m {}\033[00m" .format("Sequência incorreta"))
            print("\033[96m {}\033[00m" .format(f"Fim da função em {time.time()}"))
            return

        if flags & FLAGS_FIN == FLAGS_FIN:
            print("\033[91m {}\033[00m" .format("Recebendo flag de fechamento"))
            
            payload = b""

            self.ack_no = new_ack_no = seq_no + 1 + len(payload)
            self.seq_no = new_seq_no = ack_no
            self.flags = new_flags = FLAGS_ACK

            (dst_addr, dst_port, src_addr, src_port) = self.id_conexao
            header = make_header(src_port, dst_port, new_seq_no, new_ack_no, new_flags)
            segment = fix_checksum(header, src_addr, dst_addr)

            self.servidor.rede.enviar(segment, dst_addr)

            self.callback(self, payload)
            print("\033[96m {}\033[00m" .format(f"Fim da função em {time.time()}"))
            return

        if flags & FLAGS_ACK == FLAGS_ACK and len(payload) == 0:

            print("\033[91m {}\033[00m" .format("ACK recebido"))

            self.ack_no = seq_no
            self.seq_no = ack_no

            # print("\033[91m {}\033[00m" .format(f"-> ACK = {self.ack_no}\n -> SEQ = {self.seq_no}"))
            # print("\033[91m {}\033[00m" .format(f"-> {self.ack_no / MSS}\n -> {self.seq_no / MSS}"))

            if self.not_acked_segments:
                # time_send_seq = self.not_acked_segments[0][2]

                # if self.not_acked_segments[0][3]:
                #     self.cwnd += MSS

                self.compute_TimeoutInterval(time_recv_ack)

                self.recv_acks += 1
                self.cwnd += 1

                self.timer.cancel()
                self.timer_active = False
                self.not_acked_segments.pop(0)

                self.window_occupation -= 1

                # self.recv_acks += 1
                print("\033[91m {}\033[00m" .format(f"AKCs recebidos -> {self.recv_acks}"))
                print("\033[91m {}\033[00m" .format(f"Tamanho dos dados que ainda precisam ser enviados -> {len(self.remaining_data)} ou {len(self.remaining_data) / MSS}"))
                # self.cwnd += 1
                # if self.remaining_data != b'':
                # if len(self.remaining_data):
                #     print("\033[91m {}\033[00m" .format("Ainda faltam dados para serem enviados!"))
                #     self.enviar(self.remaining_data)

            # se ainda existirem pacotes aguardando confirmação solta o timer
            if self.not_acked_segments:
                
                self.timer = asyncio.get_event_loop().call_later(self.TimeoutInterval, self.timeout)
                self.timer_active = True

            # print("\033[96m {}\033[00m" .format(f"Fim da função em {time.time()}"))
            print("\033[91m {}\033[00m" .format(f"Ainda faltam {len(self.not_acked_segments)} seguimentos receber ACK."))
            
            # if len(self.not_acked_segments) == 0:
            # if self.recv_acks == self.cwnd:
            #     self.recv_acks = 0
            #     self.cwnd += 1
            #     print("\033[91m {}\033[00m" .format(f"Dados que faltam ser enviados -> {self.remaining_data}"))
            #     if len(self.remaining_data):
            #         self.enviar(self.remaining_data)
            
            return
        
        print("\033[91m {}\033[00m" .format("Segmento reconhecido"))
        print("\033[91m {}\033[00m" .format("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"))

        self.ack_no = new_ack_no = seq_no + len(payload)
        self.seq_no = new_seq_no = ack_no
        self.flags = new_flags = FLAGS_ACK

        # print("\033[91m {}\033[00m" .format("Reconhecido"))
        # print("\033[91m {}\033[00m" .format(f"-> {payload}"))

        # print(f"ack_no = {ack_no}, new_ack_no = {new_ack_no}")
        # print(f"seq_no = {seq_no}, new_seq_no = {new_seq_no}")
        # print()

        (dst_addr, dst_port, src_addr, src_port) = self.id_conexao
        header = make_header(src_port, dst_port, new_seq_no, new_ack_no, new_flags)
        segment = fix_checksum(header, src_addr, dst_addr)

        self.servidor.rede.enviar(segment, dst_addr)

        self.callback(self, payload)

        # print("\033[96m {}\033[00m" .format(f"Fim da função em {time.time()}"))

    # Os métodos abaixo fazem parte da API

    def registrar_recebedor(self, callback):
        """
        Usado pela camada de aplicação para registrar uma função para ser chamada
        sempre que dados forem corretamente recebidos
        """
        self.callback = callback

    def enviar(self, dados):
        """
        Usado pela camada de aplicação para enviar dados
        """
        # TODO: implemente aqui o envio de dados.
        # Chame self.servidor.rede.enviar(segmento, dest_addr) para enviar o segmento
        # que você construir para a camada de rede.

        # print("\033[95m {}\033[00m" .format(dados))
        print("\033[95m {}\033[00m" .format("Enviando dados"))
        print("\033[95m {}\033[00m" .format(f"Janela de tamanho {self.cwnd}"))

        (dst_addr, dst_port, src_addr, src_port) = self.id_conexao

        # if dados:
        #     buffer = dados
        # else:
        #     buffer = self.remaining_data

        buffer = dados
        
        # payload_size = len(dados) // self.cwnd

        while len(buffer) > 0:
        # for i in range(self.cwnd - len(self.not_acked_segments)):
        # for i in range(self.cwnd - self.window_occupation):
        # for i in range(self.cwnd):
        # Inicio do loop
            self.count_seg += 1
            print("\033[95m {}\033[00m" .format(f"-> Enviando segmento {self.count_seg}"))
            # print("\033[95m {}\033[00m" .format(f"Tipo de dado {type(buffer)}"))

            payload = buffer[:MSS]
            buffer = buffer[MSS:]
            
            # self.remaining_data[:] = buffer[:]
            # print("\033[95m {}\033[00m" .format(f"Buffer salvo {self.remaining_data}"))

            header = make_header(src_port, dst_port, self.seq_no, self.ack_no, FLAGS_ACK)
            segment = fix_checksum(header + payload, src_addr, dst_addr)

            self.servidor.rede.enviar(segment, dst_addr)

            self.seq_no += len(payload)

            self.timer = asyncio.get_event_loop().call_later(self.TimeoutInterval, self.timeout)
            self.timer_on = True

            # isWhole_window = True if self.cwnd == MSS else False
            # send_time = time.time()
            # self.not_acked_segments.append([segment, dst_addr, send_time, isWhole_window])
            self.not_acked_segments.append([segment, dst_addr, time.time()])


        self.window_occupation += self.cwnd
        # Fim do loop
        self.remaining_data = bytearray()
        self.remaining_data.extend(buffer)
        # print("\033[95m {}\033[00m" .format(f"Buffer salvo {self.remaining_data}"))


    def timeout(self):

        if self.not_acked_segments:
            print("\033[93m {}\033[00m" .format("--> Timeout! Reenviando segmento..."))

            self.cwnd = self.cwnd - self.cwnd // 2
            # self.cwnd = (self.cwnd + 1)//2
            # self.cwnd = max(MSS, self.cwnd // 2)
            # self.not_acked_segments[0][3] = False

            print("\033[93m {}\033[00m" .format(f"Janela de tamanho {self.cwnd}"))


            segment = self.not_acked_segments[0][0]
            dst_addr = self.not_acked_segments[0][1]

            # print("\033[93m {}\033[00m" .format(f"-> {self.not_acked_segments[0][2]}"))

            # send_time = time.time()

            self.servidor.rede.enviar(segment, dst_addr)

            # self.not_acked_segments[0][2] = send_time

            self.timer = asyncio.get_event_loop().call_later(self.TimeoutInterval, self.timeout)
            self.timer_on = True

            self.not_acked_segments[0][2] = None
    
    def compute_TimeoutInterval(self, time_recv_ack):

        time_send_seq = self.not_acked_segments[0][2]
        # time_recv_ack = time.time()

        # print("\033[94m {}\033[00m" .format(f"Momento de send em {time_send_seq}"))

        if time_send_seq:
            # print("\033[94m {}\033[00m" .format(f"Momento de envio do segmento: {time_send_seq}"))
            self.SampleRTT = time_recv_ack - time_send_seq
            # self.SampleRTT *= 787/815
            # print("\033[94m {}\033[00m" .format(f"Sample RTT calculado =       {self.SampleRTT}"))
        else:
            # print("\033[94m {}\033[00m" .format("Segmento foi reenviado."))
            return False

        if self.EstimatedRTT == None:
            self.EstimatedRTT = self.SampleRTT
            self.DevRTT = self.SampleRTT / 2
        else:
            self.EstimatedRTT = (1 - self.alpha) * self.EstimatedRTT + self.alpha * self.SampleRTT
            self.DevRTT = (1 - self.beta) * self.DevRTT + self.beta * abs(self.SampleRTT - self.EstimatedRTT)
        
        self.TimeoutInterval = self.EstimatedRTT + 4 * self.DevRTT

        # print("\033[94m {}\033[00m" .format(f"Estimated RTT calculado =    {self.EstimatedRTT}"))
        # print("\033[94m {}\033[00m" .format(f"Dev RTT calculado =          {self.DevRTT}"))
        # print("\033[94m {}\033[00m" .format(f"Timeout Interval calculado = {self.TimeoutInterval}"))

        return True

    def fechar(self):
        """
        Usado pela camada de aplicação para fechar a conexão
        """
        # TODO: implemente aqui o fechamento de conexão

        print("\033[93m {}\033[00m" .format("Mandando flag de fechamento"))

        (dst_addr, dst_port, src_addr, src_port) = self.id_conexao
        header = make_header(src_port, dst_port, self.seq_no, self.ack_no, FLAGS_FIN)
        segment = fix_checksum(header, src_addr, dst_addr)

        self.servidor.rede.enviar(segment, dst_addr)

        self.callback(self, b"")

        del self.servidor.conexoes[self.id_conexao]
