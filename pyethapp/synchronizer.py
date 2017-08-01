from gevent.event import AsyncResult
import gevent
import time
from eth_protocol import TransientBlockBody, TransientBlock
from ethereum.blocks import BlockHeader
from ethereum.slogging import get_logger
import ethereum.utils as utils
import traceback
from itertools import cycle

log = get_logger('eth.sync')
log_st = get_logger('eth.sync.task')


class SyncTask(object):

    """
    synchronizes a the chain starting from a given blockhash
    blockchain hash is fetched from a single peer (which led to the unknown blockhash)
    blocks are fetched from the best peers

    with missing block:
        fetch headers
            until known block
    for headers
        fetch block bodies
            for each block body
                construct block
                chainservice.add_blocks() # blocks if queue is full
    """
    initial_blockheaders_per_request = 32
    max_blockheaders_per_request = 192
    max_skeleton_size = 128
    max_blocks_per_request = 128
    max_retries = 16
    retry_delay = 2.
    blocks_request_timeout = 8.
    blockheaders_request_timeout = 19.
    

    def __init__(self, synchronizer, proto, blockhash, chain_difficulty=0, originator_only=False):
        self.synchronizer = synchronizer
        self.chain = synchronizer.chain
        self.chainservice = synchronizer.chainservice
        self.originating_proto = proto
        self.skeleton_peer = None 
        self.originator_only = originator_only
        self.blockhash = blockhash
        self.chain_difficulty = chain_difficulty
        self.requests = dict()  # proto: Event
        self.header_request = None
        self.batch_requests = [] #batch header request 
        self.start_block_number = self.chain.head.number
        self.end_block_number = self.start_block_number + 1  # minimum synctask
        self.max_block_revert = 3600*24 / self.chainservice.config['eth']['block']['DIFF_ADJUSTMENT_CUTOFF']
        self.start_block_number_min = max(self.chain.head.number-self.max_block_revert, 0)
        gevent.spawn(self.run)

    def run(self):
        log_st.info('spawning new synctask')
        try:
            self.fetch_hashchain()
        except Exception:
            print(traceback.format_exc())
            self.exit(success=False)

    def exit(self, success=False):
        if not success:
            log_st.warn('syncing failed')
        else:
            log_st.debug('successfully synced')
        self.synchronizer.synctask_exited(success)

    @property
    def protocols(self):
        if self.originator_only:
            return [self.originating_proto]
        return self.synchronizer.protocols

    def fetch_hashchain(self):
       # local_blockhash=
       # from=commonancestor(self.blockhash,local_blockhash)
        skeleton = []
        header_batch = []
        skeleton_fetch_done=False 
        from0 = self.chain.head.number

        log_st.debug('current block number:%u', from0, origin=self.originating_proto)
        while not skeleton_fetch_done:
        # Get skeleton headers
            deferred = AsyncResult()
            protos = self.protocols 
            if not protos:
                log_st.warn('no protocols available')
                self.exit(False)
            if self.originating_proto.is_stopped:
                self.skeleton_peer= protos[0] 
            else:
                self.skeleton_peer=self.originating_proto  
            self.requests[self.skeleton_peer] = deferred 
            self.skeleton_peer.send_getblockheaders(from0+self.max_blockheaders_per_request,self.max_skeleton_size,self.max_blockheaders_per_request-1,0)  
            try:
                   skeleton = deferred.get(block=True,timeout=self.blockheaders_request_timeout)
                 #  assert isinstance(skeleton,list)
                 #  log_st.debug('skeleton received %u',len(skeleton))  
            except gevent.Timeout:
                   log_st.warn('syncing skeleton timed out')
                 #todo drop originating proto 
                   self.exit(False)
            finally:
                #                    # is also executed 'on the way out' when any other clause of the try statement
                #                    # is left via a break, continue or return statement.
                #                    del self.requests[proto]
                   #del self.requests[self.originating_proto]
                   del self.requests[self.skeleton_peer]

                    
            log_st.debug('skeleton received',num= len(skeleton), skeleton=skeleton)  
                   
            if not skeleton:
         #      self.fetch_headers(from0)
         #      skeleton_fetch_done = True 
               continue
            else:
               self.fetch_headerbatch(skeleton)
                 # processed= process_headerbatch(batch_header)
                 # self.batch_header = filled[:processed]
                 # fetch_blocks(header_batch)
            from0 = from0 + self.max_skeleton_size*self.max_blockheaders_per_request   
       #insert batch_header to hashchain      
               
#send requests in batches, receive one header batch at a time    
    def fetch_headerbatch(self, skeleton):
        
        
        # while True   
        from0=skeleton[0]
        self.batch_requests=[]
        batch_result= ['']*self.max_skeleton_size*self.max_blockheaders_per_request
        headers= []
        proto = None
        proto_received=None #proto which delivered the header
        retry = 0
        received = False
        for header in skeleton:
            self.batch_requests.append(header)
        
        #requests = cycle(self.batch_requests)
        # while there are unanswered requests
        

        while True:
 #           requests = cycle(batch_requests)
         requests = iter(self.batch_requests)
         deferred = AsyncResult()
   #         self.header_request=deferred
           # should check if there is idle proto
         
       #  if not self.idle_protocols():
       #      continue
         for proto in self.idle_protocols():
           #        
              # self.requests[proto] = next(requests)   
               # check if it's finished
             if self.batch_requests:
                 try:
                     start=next(requests).number  
                 except StopIteration:
                     start=self.batch_requests[0]

                 self.requests[proto] = deferred 
                 proto.send_getblockheaders(start,self.max_blockheaders_per_request)
                 proto.idle = False 
                 log_st.debug('sent header request',request= start , proto=proto) 
             else:
               log_st.debug('batch header fetching done')
               return True 
         try:
               proto_received = deferred.get(timeout=self.blockheaders_request_timeout)
               log_st.debug('headers batch received from proto',proto=proto_received)
               del self.requests[proto_received]    
         except gevent.Timeout:
               log_st.warn('syncing batch hashchain timed out')
               retry += 1
               if retry >= self.max_retries:
                    log_st.warn('headers sync failed with all peers',
                            num_protos=len(self.idle_protocols()))
                    return self.exit(success=False)
               else:
                    log_st.info('headers sync failed with peers, retry', retry=retry)
                    gevent.sleep(self.retry_delay)
                    continue

                 
               #verify the header and deliver it to the next step 
         #      self.verify_headers(proto,headers)
         #pack batch headers  
         #      for header in range[headers]:
         #          batch_result.insert(headers[0]-from0,header)

               #send to header processor/body downloader 
              # self.deliver(headers)
        return batch_result   

    def idle_protocols(self):
        idle = []
        for proto in self.protocols:
            if proto.idle:
               idle.append(proto)
        return idle        


    def verify_headers(self,proto,headers):
        request= self.peer_requests[proto];
       # if request:
       #    return 0, errNoFetchesPending
         

   
    def fetch_headers(self,proto, fromx):
        deferred = AsyncResult()
        proto.send_getblockheaders(fromx,self.max_blockheaders_per_request)
        try:
            blockheaders_batch = deferred.get(block=True,timeout=self.blockheaders_request_timeout)
        except gevent.Timeout:
            log_st.warn('syncing batch hashchain timed out')
            self.exit()
        finally:
            return blockheaders_batch
        

#    def fetch_hashchain(self):
#        log_st.debug('fetching hashchain')
#        blockheaders_chain = [] # height falling order
#        blockhash = self.blockhash
#         assert blockhash not in self.chain

        # get block hashes until we found a known one
#        retry = 0
#        max_blockheaders_per_request = self.initial_blockheaders_per_request
#        while blockhash not in self.chain:
#            # proto with highest_difficulty should be the proto we got the newblock from
#            blockheaders_batch = []
#
#            # try with protos
#            protocols = self.protocols
#            if not protocols:
#                log_st.warn('no protocols available')
#                return self.exit(success=False)
#
#            for proto in protocols:
#                log.debug('syncing with', proto=proto)
#                if proto.is_stopped:
#                    continue
#
#                # request
#                assert proto not in self.requests
#                deferred = AsyncResult()
#                self.requests[proto] = deferred
#                proto.send_getblockheaders(blockhash, max_blockheaders_per_request)
#                try:
#                    blockheaders_batch = deferred.get(block=True,
#                                                      timeout=self.blockheaders_request_timeout)
#                except gevent.Timeout:
#                    log_st.warn('syncing hashchain timed out')
#                    continue
#                finally:
#                    # is also executed 'on the way out' when any other clause of the try statement
#                    # is left via a break, continue or return statement.
#                    del self.requests[proto]
#
#                if not blockheaders_batch:
#                    log_st.warn('empty getblockheaders result')
#                    continue
#                if not all(isinstance(bh, BlockHeader) for bh in blockheaders_batch):
#                    log_st.warn('got wrong data type', expected='BlockHeader',
#                                received=type(blockheaders_batch[0]))
#                    continue
#                break
#
#            if not blockheaders_batch:
#                retry += 1
#                if retry >= self.max_retries:
#                    log_st.warn('headers sync failed with all peers', num_protos=len(protocols))
#                    return self.exit(success=False)
#                else:
#                    log_st.info('headers sync failed with peers, retry', retry=retry)
#                    gevent.sleep(self.retry_delay)
#                    continue
#            retry = 0
#
#            for header in blockheaders_batch:  # youngest to oldest
#                blockhash = header.hash
#                if blockhash not in self.chain:
#                    if header.number <= self.start_block_number_min:
#                        # We have received so many headers that a very unlikely big revert will happen,
#                        # which is nearly impossible.
#                        log_st.warn('syncing failed with endless headers',
#                                    end=header.number, len=len(blockheaders_chain))
#                        return self.exit(success=False)
#                    elif len(blockheaders_chain) == 0 or blockheaders_chain[-1].prevhash == header.hash:
#                        blockheaders_chain.append(header)
#                    else:
#                        log_st.warn('syncing failed because discontinuous header received',
#                                    child=blockheaders_chain[-1], parent=header)
#                        return self.exit(success=False)
#                else:
#                    log_st.debug('found known block header', blockhash=utils.encode_hex(blockhash),
#                                 is_genesis=bool(blockhash == self.chain.genesis.hash))
#                    break
#            else:  # if all headers in batch added to blockheaders_chain
#                blockhash = header.prevhash
#
#            start = "#%d %s" % (blockheaders_chain[0].number, utils.encode_hex(blockheaders_chain[0].hash)[:8])
#            end = "#%d %s" % (blockheaders_chain[-1].number, utils.encode_hex(blockheaders_chain[-1].hash)[:8])
#            log_st.info('downloaded ' + str(len(blockheaders_chain)) + ' blockheaders', start=start, end=end)
#            self.end_block_number = self.chain.head.number + len(blockheaders_chain)
#            max_blockheaders_per_request = self.max_blockheaders_per_request
#
#        self.start_block_number = self.chain.get(blockhash).number
#        self.end_block_number = self.chain.get(blockhash).number + len(blockheaders_chain)
#        log_st.debug('computed missing numbers', start_number=self.start_block_number, end_number=self.end_block_number)
#        self.fetch_blocks(blockheaders_chain)

    def fetch_blocks(self, blockheaders_chain):
        # fetch blocks (no parallelism here)
        log_st.debug('fetching blocks', num=len(blockheaders_chain))
        assert blockheaders_chain
        blockheaders_chain.reverse()  # height rising order
        num_blocks = len(blockheaders_chain)
        num_fetched = 0
        retry = 0
        while blockheaders_chain:
            blockhashes_batch = [h.hash for h in blockheaders_chain[:self.max_blocks_per_request]]
            bodies = []

            # try with protos
            protocols = self.protocols
            if not protocols:
                log_st.warn('no protocols available')
                return self.exit(success=False)

            for proto in protocols:
                if proto.is_stopped:
                    continue
                assert proto not in self.requests
                # request
                log_st.debug('requesting blocks', num=len(blockhashes_batch), missing=len(blockheaders_chain)-len(blockhashes_batch))
                deferred = AsyncResult()
                self.requests[proto] = deferred
                proto.send_getblockbodies(*blockhashes_batch)
                try:
                    bodies = deferred.get(block=True, timeout=self.blocks_request_timeout)
                except gevent.Timeout:
                    log_st.warn('getblockbodies timed out, trying next proto')
                    continue
                finally:
                    del self.requests[proto]
                if not bodies:
                    log_st.warn('empty getblockbodies reply, trying next proto')
                    continue
                elif not isinstance(bodies[0], TransientBlockBody):
                    log_st.warn('received unexpected data')
                    bodies = []
                    continue

            # add received t_blocks
            num_fetched += len(bodies)
            log_st.debug('received block bodies', num=len(bodies), num_fetched=num_fetched,
                         total=num_blocks, missing=num_blocks - num_fetched)

            if not bodies:
                retry += 1
                if retry >= self.max_retries:
                    log_st.warn('bodies sync failed with all peers', missing=len(blockheaders_chain))
                    return self.exit(success=False)
                else:
                    log_st.info('bodies sync failed with peers, retry', retry=retry)
                    gevent.sleep(self.retry_delay)
                    continue
            retry = 0

            ts = time.time()
            log_st.debug('adding blocks', qsize=self.chainservice.block_queue.qsize())
            for body in bodies:
                try:
                    h = blockheaders_chain.pop(0)
                    t_block = TransientBlock(h, body.transactions, body.uncles)
                    self.chainservice.add_block(t_block, proto)  # this blocks if the queue is full
                except IndexError as e:
                    log_st.error('headers and bodies mismatch', error=e)
                    self.exit(success=False)
            log_st.debug('adding blocks done', took=time.time() - ts)

        # done
        last_block = t_block
        assert not len(blockheaders_chain)
        assert last_block.header.hash == self.blockhash
        log_st.debug('syncing finished')
        # at this point blocks are not in the chain yet, but in the add_block queue
        if self.chain_difficulty >= self.chain.head.chain_difficulty():
            self.chainservice.broadcast_newblock(last_block, self.chain_difficulty, origin=proto)

        self.exit(success=True)

    def receive_newblockhashes(self, proto, newblockhashes):
        """
        no way to check if this really an interesting block at this point.
        might lead to an amplification attack, need to track this proto and judge usefullness
        """
        log.debug('received newblockhashes', num=len(newblockhashes), proto=proto)
        # log.debug('DISABLED')
        # return
        newblockhashes = [h.hash for h in newblockhashes if not self.chainservice.knows_block(h.hash)]
        if (proto not in self.protocols) or (not newblockhashes) or self.synctask:
            log.debug('discarding', known=bool(not newblockhashes), synctask=bool(self.synctask))
            return
        if len(newblockhashes) != 1:
            log.warn('supporting only one newblockhash', num=len(newblockhashes))
        if not self.chainservice.is_syncing:
            blockhash = newblockhashes[0]
            log.debug('starting synctask for newblockhashes', blockhash=blockhash.encode('hex'))
            self.synctask = SyncTask(self, proto, blockhash, 0, originator_only=True)




    def receive_blockbodies(self, proto, bodies):
        log.debug('block bodies received', proto=proto, num=len(bodies))
        if proto not in self.requests:
            log.debug('unexpected blocks')
            return
        self.requests[proto].set(bodies)


    def receive_blockheaders(self, proto, blockheaders):
        log.debug('blockheaders received:', proto=proto, num=len(blockheaders), blockheaders=blockheaders)
        if proto not in self.requests:
           log.debug('unexpected blockheaders')
           return
        if self.batch_requests and blockheaders:
            if blockheaders[0] in self.batch_requests:
              self.batch_requests.remove(blockheaders[0])
            log_st.debug('remaining headers',num=len(self.batch_requests),headers=self.batch_requests)
            proto.set_idle() 
            self.requests[proto].set(proto)
        elif proto == self.skeleton_peer: #make sure it's from the originating proto 
            self.requests[proto].set(blockheaders)
     #   self.header_request.set(blockheaders)
        
         

         


class Synchronizer(object):

    """
    handles the synchronization of blocks

    there is only one synctask active at a time
    in order to deal with the worst case of initially syncing the wrong chain,
        a checkpoint blockhash can be specified and synced via force_sync

    received blocks are given to chainservice.add_block
    which has a fixed size queue, the synchronization blocks if the queue is full

    on_status:
        if peer.head.chain_difficulty > chain.head.chain_difficulty
            fetch peer.head and handle as newblock
    on_newblock:
        if block.parent:
            add
        else:
            sync
    on_blocks/on_blockhashes:
        if synctask:
            handle to requester
        elif unknown and has parent:
            add to chain
        else:
            drop
    """

    MAX_NEWBLOCK_AGE = 5  # maximum age (in blocks) of blocks received as newblock

    def __init__(self, chainservice, force_sync=None):
        """
        @param: force_sync None or tuple(blockhash, chain_difficulty)
                helper for long initial syncs to get on the right chain
                used with first status_received
        """
        self.chainservice = chainservice
        self.force_sync = force_sync
        self.chain = chainservice.chain
        self._protocols = dict()  # proto: chain_difficulty
        self.synctask = None

    def synctask_exited(self, success=False):
        # note: synctask broadcasts best block
        if success:
            self.force_sync = None
        self.synctask = None

    @property
    def protocols(self):
        "return protocols which are not stopped sorted by highest chain_difficulty"
        # filter and cleanup
        self._protocols = dict((p, cd) for p, cd in self._protocols.items() if not p.is_stopped)
        return sorted(self._protocols.keys(), key=lambda p: self._protocols[p], reverse=True)


    def receive_newblock(self, proto, t_block, chain_difficulty):
        "called if there's a newblock announced on the network"
        log.debug('newblock', proto=proto, block=t_block, chain_difficulty=chain_difficulty,
                  client=proto.peer.remote_client_version)

        if t_block.header.hash in self.chain:
            assert chain_difficulty == self.chain.get(t_block.header.hash).chain_difficulty()

        # memorize proto with difficulty
        self._protocols[proto] = chain_difficulty

        if self.chainservice.knows_block(block_hash=t_block.header.hash):
            log.debug('known block')
            return

        # check pow
        if not t_block.header.check_pow():
            log.warn('check pow failed, should ban!')
            return

        expected_difficulty = self.chain.head.chain_difficulty() + t_block.header.difficulty
        if chain_difficulty >= self.chain.head.chain_difficulty():
            # broadcast duplicates filtering is done in eth_service
            log.debug('sufficient difficulty, broadcasting',
                      client=proto.peer.remote_client_version)
            self.chainservice.broadcast_newblock(t_block, chain_difficulty, origin=proto)
        else:
            # any criteria for which blocks/chains not to add?
            age = self.chain.head.number - t_block.header.number
            log.debug('low difficulty', client=proto.peer.remote_client_version,
                      chain_difficulty=chain_difficulty, expected_difficulty=expected_difficulty,
                      block_age=age)
            if age > self.MAX_NEWBLOCK_AGE:
                log.debug('newblock is too old, not adding', block_age=age,
                          max_age=self.MAX_NEWBLOCK_AGE)
                return

        # unknown and pow check and highest difficulty

        # check if we have parent
        if self.chainservice.knows_block(block_hash=t_block.header.prevhash):
            log.debug('adding block')
            self.chainservice.add_block(t_block, proto)
        else:
            log.debug('missing parent for new block', block=t_block)
            if not self.synctask:
                self.synctask = SyncTask(self, proto, t_block.header.hash, chain_difficulty)
            else:
                log.debug('already syncing, won\'t start new sync task')

    def receive_status(self, proto, blockhash, chain_difficulty):
        "called if a new peer is connected"
        log.debug('status received', proto=proto, chain_difficulty=chain_difficulty)

        # memorize proto with difficulty
        self._protocols[proto] = chain_difficulty

        if self.chainservice.knows_block(blockhash) or self.synctask:
            log.debug('existing task or known hash, discarding')
            return

        if self.force_sync:
            blockhash, chain_difficulty = self.force_sync
            log.debug('starting forced syctask', blockhash=blockhash.encode('hex'))
            self.synctask = SyncTask(self, proto, blockhash, chain_difficulty)

        elif chain_difficulty > self.chain.head.chain_difficulty():
            log.debug('sufficient difficulty')
            self.synctask = SyncTask(self, proto, blockhash, chain_difficulty)




    def receive_blockbodies(self, proto, bodies):
        log.debug('blockbodies received', proto=proto, num=len(bodies))
        if self.synctask:
            self.synctask.receive_blockbodies(proto, bodies)
        else:
            log.warn('no synctask, not expecting block bodies')

    def receive_blockheaders(self, proto, blockheaders):
        log.debug('blockheaders received', proto=proto, num=len(blockheaders))
        if self.synctask:
            self.synctask.receive_blockheaders(proto, blockheaders)
        else:
            log.warn('no synctask, not expecting blockheaders')
