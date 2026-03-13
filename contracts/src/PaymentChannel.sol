// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "forge-std/interfaces/IERC20.sol";

/**
 * @title PaymentChannel
 * @notice Unidirectional payment channel for agentic micropayments.
 *         Supports both native ETH and ERC-20 token deposits.
 *
 * Flow:
 *   1. Sender opens channel with ETH deposit (or ERC-20 via approve + openTokenChannel)
 *   2. Off-chain: sender signs vouchers (nonce, cumulative amount)
 *   3. Receiver submits highest-nonce voucher to close
 *   4. Challenge period allows dispute with higher-nonce voucher
 *   5. After challenge period, funds are released via withdraw
 */
contract PaymentChannel {
    struct Channel {
        address sender;
        address receiver;
        uint256 deposit;
        uint256 closingNonce;
        uint256 closingAmount;
        uint256 expiration; // challenge period end timestamp
        bool closed;
        address token; // address(0) = native ETH, otherwise ERC-20
    }

    uint256 public constant MIN_CHALLENGE_PERIOD = 1 hours;

    mapping(bytes32 => Channel) public channels;

    event ChannelOpened(bytes32 indexed channelId, address indexed sender, address indexed receiver, uint256 deposit);
    event TokenChannelOpened(
        bytes32 indexed channelId, address indexed sender, address indexed receiver, uint256 deposit, address token
    );
    event ChannelCloseInitiated(bytes32 indexed channelId, uint256 amount, uint256 expiration);
    event ChannelChallenged(bytes32 indexed channelId, uint256 amount, uint256 nonce);
    event ChannelClosed(bytes32 indexed channelId, uint256 amount);

    /**
     * @notice Open a new payment channel with native ETH.
     * @param receiver The payment receiver address.
     * @param duration Challenge period duration in seconds.
     * @return channelId The unique channel identifier.
     */
    function openChannel(address receiver, uint256 duration) external payable returns (bytes32 channelId) {
        require(msg.value > 0, "Deposit required");
        require(receiver != address(0), "Invalid receiver");
        require(receiver != msg.sender, "Cannot pay self");
        require(duration >= MIN_CHALLENGE_PERIOD, "Duration too short");

        channelId = keccak256(abi.encodePacked(msg.sender, receiver, block.timestamp, msg.value));
        require(channels[channelId].deposit == 0, "Channel exists");

        channels[channelId] = Channel({
            sender: msg.sender,
            receiver: receiver,
            deposit: msg.value,
            closingNonce: 0,
            closingAmount: 0,
            expiration: 0,
            closed: false,
            token: address(0)
        });

        emit ChannelOpened(channelId, msg.sender, receiver, msg.value);
    }

    /**
     * @notice Open a new payment channel with an ERC-20 token.
     * @dev Sender must approve this contract for `amount` tokens first.
     * @param receiver The payment receiver address.
     * @param duration Challenge period duration in seconds.
     * @param token The ERC-20 token contract address.
     * @param amount The token deposit amount.
     * @return channelId The unique channel identifier.
     */
    function openTokenChannel(address receiver, uint256 duration, address token, uint256 amount)
        external
        returns (bytes32 channelId)
    {
        require(amount > 0, "Deposit required");
        require(receiver != address(0), "Invalid receiver");
        require(receiver != msg.sender, "Cannot pay self");
        require(token != address(0), "Invalid token");
        require(duration >= MIN_CHALLENGE_PERIOD, "Duration too short");

        // Transfer tokens from sender to this contract
        bool success = IERC20(token).transferFrom(msg.sender, address(this), amount);
        require(success, "Token transfer failed");

        channelId = keccak256(abi.encodePacked(msg.sender, receiver, block.timestamp, amount, token));
        require(channels[channelId].deposit == 0, "Channel exists");

        channels[channelId] = Channel({
            sender: msg.sender,
            receiver: receiver,
            deposit: amount,
            closingNonce: 0,
            closingAmount: 0,
            expiration: 0,
            closed: false,
            token: token
        });

        emit TokenChannelOpened(channelId, msg.sender, receiver, amount, token);
    }

    /**
     * @notice Initiate channel close with a signed voucher.
     * @param channelId The channel to close.
     * @param amount Cumulative payment amount from voucher.
     * @param nonce Voucher nonce.
     * @param timestamp Voucher timestamp.
     * @param signature Sender's ECDSA signature.
     */
    function closeChannel(bytes32 channelId, uint256 amount, uint256 nonce, uint256 timestamp, bytes calldata signature)
        external
    {
        Channel storage ch = channels[channelId];
        require(ch.deposit > 0, "Channel not found");
        require(!ch.closed, "Already closed");
        require(msg.sender == ch.receiver, "Only receiver can close");
        require(amount <= ch.deposit, "Amount exceeds deposit");

        // Verify sender's signature on the voucher
        bytes32 msgHash = keccak256(abi.encodePacked(channelId, nonce, amount, timestamp));
        bytes32 ethSignedHash = _toEthSignedMessageHash(msgHash);
        require(_recover(ethSignedHash, signature) == ch.sender, "Invalid signature");

        ch.closingNonce = nonce;
        ch.closingAmount = amount;
        ch.expiration = block.timestamp + MIN_CHALLENGE_PERIOD;

        emit ChannelCloseInitiated(channelId, amount, ch.expiration);
    }

    /**
     * @notice Challenge a close with a higher-nonce voucher.
     * @param channelId The channel being challenged.
     * @param amount Cumulative amount from the newer voucher.
     * @param nonce Must be higher than the current closing nonce.
     * @param timestamp Voucher timestamp.
     * @param signature Sender's ECDSA signature.
     */
    function challengeClose(
        bytes32 channelId,
        uint256 amount,
        uint256 nonce,
        uint256 timestamp,
        bytes calldata signature
    ) external {
        Channel storage ch = channels[channelId];
        require(ch.expiration > 0, "Not closing");
        require(block.timestamp < ch.expiration, "Challenge period ended");
        require(nonce > ch.closingNonce, "Nonce not higher");
        require(amount <= ch.deposit, "Amount exceeds deposit");

        bytes32 msgHash = keccak256(abi.encodePacked(channelId, nonce, amount, timestamp));
        bytes32 ethSignedHash = _toEthSignedMessageHash(msgHash);
        require(_recover(ethSignedHash, signature) == ch.sender, "Invalid signature");

        ch.closingNonce = nonce;
        ch.closingAmount = amount;
        // Reset challenge period
        ch.expiration = block.timestamp + MIN_CHALLENGE_PERIOD;

        emit ChannelChallenged(channelId, amount, nonce);
    }

    /**
     * @notice Withdraw funds after challenge period expires.
     * @param channelId The channel to withdraw from.
     */
    function withdraw(bytes32 channelId) external {
        Channel storage ch = channels[channelId];
        require(ch.expiration > 0, "Not closing");
        require(block.timestamp >= ch.expiration, "Challenge period active");
        require(!ch.closed, "Already withdrawn");

        ch.closed = true;
        uint256 receiverAmount = ch.closingAmount;
        uint256 senderRefund = ch.deposit - receiverAmount;

        if (ch.token == address(0)) {
            // Native ETH settlement
            if (receiverAmount > 0) {
                payable(ch.receiver).transfer(receiverAmount);
            }
            if (senderRefund > 0) {
                payable(ch.sender).transfer(senderRefund);
            }
        } else {
            // ERC-20 token settlement
            IERC20 token = IERC20(ch.token);
            if (receiverAmount > 0) {
                require(token.transfer(ch.receiver, receiverAmount), "Receiver transfer failed");
            }
            if (senderRefund > 0) {
                require(token.transfer(ch.sender, senderRefund), "Sender refund failed");
            }
        }

        emit ChannelClosed(channelId, receiverAmount);
    }

    /**
     * @notice Query channel state.
     */
    function getChannel(bytes32 channelId)
        external
        view
        returns (
            address sender,
            address receiver,
            uint256 deposit,
            uint256 closingNonce,
            uint256 closingAmount,
            uint256 expiration,
            bool closed
        )
    {
        Channel storage ch = channels[channelId];
        return (ch.sender, ch.receiver, ch.deposit, ch.closingNonce, ch.closingAmount, ch.expiration, ch.closed);
    }

    /**
     * @notice Query channel token address (address(0) = native ETH).
     */
    function getChannelToken(bytes32 channelId) external view returns (address) {
        return channels[channelId].token;
    }

    function _toEthSignedMessageHash(bytes32 hash) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", hash));
    }

    function _recover(bytes32 hash, bytes memory sig) internal pure returns (address) {
        require(sig.length == 65, "Invalid signature length");
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := mload(add(sig, 32))
            s := mload(add(sig, 64))
            v := byte(0, mload(add(sig, 96)))
        }
        if (v < 27) v += 27;
        return ecrecover(hash, v, r, s);
    }
}
