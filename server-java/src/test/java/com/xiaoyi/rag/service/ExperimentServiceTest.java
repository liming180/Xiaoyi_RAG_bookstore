package com.xiaoyi.rag.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xiaoyi.rag.common.exception.ApiException;
import com.xiaoyi.rag.model.dto.CreateExperimentRequest;
import com.xiaoyi.rag.model.entity.Experiment;
import com.xiaoyi.rag.repository.ExperimentRepository;
import com.xiaoyi.rag.repository.ExperimentRunRepository;
import com.xiaoyi.rag.service.impl.ExperimentServiceImpl;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;

class ExperimentServiceTest {
    private final ExperimentRepository experiments = mock(ExperimentRepository.class);
    private final ExperimentRunRepository runs = mock(ExperimentRunRepository.class);
    private final EvalService eval = mock(EvalService.class);
    private final PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
    private final ExperimentServiceImpl service;

    ExperimentServiceTest() {
        when(manager.getTransaction(any())).thenReturn(mock(TransactionStatus.class));
        service = new ExperimentServiceImpl(experiments, runs, eval, new ObjectMapper(), manager);
    }

    @Test
    void startupFailsInterruptedTasksAndPreservesCompletedGroups() {
        Experiment interrupted = new Experiment();
        interrupted.setStatus("RUNNING");
        interrupted.setFinishedGroups(1);
        when(experiments.findByStatusIn(List.of("PENDING", "RUNNING")))
                .thenReturn(List.of(interrupted));
        service.recoverInterrupted();
        assertThat(interrupted.getStatus()).isEqualTo("FAILED");
        assertThat(interrupted.getFinishedGroups()).isEqualTo(1);
        assertThat(interrupted.getFinishedAt()).isPositive();
        verify(experiments).save(interrupted);
        assertThat(service.isRunning()).isFalse();
    }

    @Test
    void rejectsBadBoundsNullValuesAndAllInvalidMatrix() {
        assertCode(() -> service.create(null), 40001);
        assertCode(() -> service.create(request(List.of(49), List.of(0), List.of(3))), 40001);
        assertCode(() -> service.create(request(List.of(1001), List.of(0), List.of(3))), 40001);
        assertCode(() -> service.create(request(List.of(180), List.of(-1), List.of(3))), 40001);
        assertCode(() -> service.create(request(List.of(180), List.of(0), List.of(11))), 40001);
        assertCode(() -> service.create(request(List.of(180), List.of(180), List.of(3))), 40004);
        assertCode(() -> service.create(request(List.of(), List.of(0), List.of(3))), 40004);
        assertThat(service.isRunning()).isFalse();
        verify(experiments, never()).saveAndFlush(any());
    }

    @Test
    void failingEvaluationMarksFailedAndReleasesLock() throws Exception {
        Experiment experiment = new Experiment();
        experiment.setName("failed");
        experiment.setStatus("RUNNING");
        experiment.setProgress(0);
        experiment.setTotalGroups(1);
        experiment.setFinishedGroups(0);
        experiment.setCreatedAt(1L);
        // Real JPA assigns an ID; use reflection only to mimic that generated field in this unit
        // test.
        var id = Experiment.class.getDeclaredField("id");
        id.setAccessible(true);
        id.set(experiment, 1L);
        when(experiments.saveAndFlush(any())).thenReturn(experiment);
        when(experiments.findById(1L)).thenReturn(java.util.Optional.of(experiment));
        when(eval.questions()).thenThrow(new IllegalStateException("provider failure"));
        CountDownLatch finished = new CountDownLatch(1);
        doAnswer(
                        invocation -> {
                            if ("FAILED"
                                    .equals(((Experiment) invocation.getArgument(0)).getStatus()))
                                finished.countDown();
                            return invocation.getArgument(0);
                        })
                .when(experiments)
                .save(any());
        service.create(request(List.of(180), List.of(0), List.of(3)));
        assertThat(finished.await(3, TimeUnit.SECONDS)).isTrue();
        // finish saves inside a transaction; wait for finally without a timing-based sleep.
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(1);
        while (service.isRunning() && System.nanoTime() < deadline) Thread.onSpinWait();
        assertThat(service.isRunning()).isFalse();
        assertThat(experiment.getStatus()).isEqualTo("FAILED");
        assertThat(experiment.getError()).isEqualTo("provider failure");
        service.assertChatAvailable();
    }

    private CreateExperimentRequest request(
            List<Integer> chunk, List<Integer> overlap, List<Integer> k) {
        return new CreateExperimentRequest(
                "test",
                new CreateExperimentRequest.ExperimentAxis(
                        chunk, overlap, k, List.of(false), List.of(false)));
    }

    private void assertCode(Runnable action, int code) {
        assertThatThrownBy(action::run)
                .isInstanceOfSatisfying(
                        ApiException.class, error -> assertThat(error.getCode()).isEqualTo(code));
    }
}
