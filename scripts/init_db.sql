CREATE DATABASE `famlvkgo_blis-perf-ci`;
USE `famlvkgo_blis-perf-ci`;

CREATE TABLE `runs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `machine` text NOT NULL,
  `config` text NOT NULL,
  `commit` text NOT NULL,
  `tag` text NOT NULL,
  `timestamp` timestamp NOT NULL,
  `comment` text DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;

CREATE TABLE `perf` (
  `run` int(11) NOT NULL,
  `gflops` double NOT NULL,
  `m` int(11) DEFAULT NULL,
  `n` int(11) DEFAULT NULL,
  `k` int(11) DEFAULT NULL,
  `op` text NOT NULL,
  `dt` char(1) NOT NULL,
  `threads` int(11) NOT NULL,
  `ir_nt` int(11) DEFAULT NULL,
  `jr_nt` int(11) DEFAULT NULL,
  `ic_nt` int(11) DEFAULT NULL,
  `jc_nt` int(11) DEFAULT NULL,
  KEY `run` (`run`),
  CONSTRAINT `run` FOREIGN KEY (`run`) REFERENCES `runs` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;

CREATE TABLE `max_perf` (
  `run` int(11) NOT NULL,
  `gflops` double NOT NULL,
  `op` text DEFAULT NULL,
  `dt` char(1) DEFAULT NULL,
  `threads` int(11) DEFAULT NULL,
  KEY `run` (`run`),
  CONSTRAINT `max_perf_ibfk_1` FOREIGN KEY (`run`) REFERENCES `runs` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;